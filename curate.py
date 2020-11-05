from time import sleep
import os
from logger import Logger, Levels
from discord import Client, DMChannel, TextChannel, Guild, Message, MessageType, utils, Intents, Embed, Activity
from discord.errors import InvalidData, HTTPException, NotFound, Forbidden
import pickle

l = Logger('Curator Core', Levels.DEBUG)

# todo: argparse, configurable run
TOKEN = os.environ.get('ART_CURATOR_TOKEN')


if TOKEN is None:
    l.fatal('Token was not provided. Use environment variable ART_CURATOR_TOKEN')

# todo separate config control, route builder, command control
class Curator(Client):
    async def notif(self, message, guild):
        chid = await self.config_get(guild.id, 'notification_channel')
        if chid is None:
            return
        ch = await self.fetch_channel(chid)
        try:
            await ch.send(message)
        except (InvalidData, HTTPException, NotFound, Forbidden) as e:
            return await self.error(f'Failed to error notify because of {e.__class__}:{e.__str__()}')

    async def answer(self, message, channel):
        try:
            await channel.send(message)
        except (InvalidData, HTTPException, NotFound, Forbidden) as e:
            return await self.error(f'Failed to error notify because of {e.__class__}:{e.__str__()}', notif=f'I couldn\'t answer someone in {channel.mention} and now I\'m sad', guild=channel.guild)

    async def error(self, message, notif=None, guild=None, channel=None, author=None):  # expecting objects for now
        l.error(message)
        if guild is not None:
            return await self.notif(message if notif is None else notif, guild)
        if channel is not None:
            return await self.answer(message, channel)
        return None

    @staticmethod
    def get_default_config():
        return {
            'sep': '#!',
            'notification_channel': None,
            'content': 'Check out what {} just published!',
            'control': [],
            'routes': []
        }

    def __init__(self):
        super(Curator, self).__init__()
        try:
            self.guild_config = pickle.load(open('guild_config.pcl', 'rb'))
            l.info(f'Loaded config')
        except (EOFError, FileNotFoundError):  # todo more possible exceptions
            l.warning(f'Recreating config')
            self.guild_config = {}



    async def auth(self, guild, user):
        auth = await self.config_get(guild.id, 'control')
        if auth.__len__() == 0:
            return True
        if user.id in auth:
            return True
        # todo: refactor
        if (set([q.id for q in user.roles])&set(auth)).__len__() > 0:
            return True
        return False

    def save_config(self):
        pickle.dump(self.guild_config, open('guild_config.pcl', 'wb'))

    def add_config(self, guild):
        self.guild_config[guild] = Curator.get_default_config()
        # todo check how async that is
        self.save_config()

    def remove_config(self, guild_id):
        del self.guild_config[guild_id]
        # todo check how async that is
        self.save_config()

    def check_config(self, guild_id):
        if guild_id not in self.guild_config:
            try:
                self.guild_config[guild_id] = Curator.get_default_config()
                self.save_config()
                return True
            except Exception: # todo fix
                return False
        else:
            return True

    # todo: protect after separation
    async def config_get(self, guild_id, key):
        if not self.check_config(guild_id):
            await self.error(f'Got config get request for {guild_id} which is not present')
            return None
        return self.guild_config[guild_id].get(key)

    async def config_set(self, guild_id, key, value):
        if not self.check_config(guild_id):
            await self.error(f'Got config set request for {guild_id} which is not present')
        self.guild_config[guild_id][key] = value
        self.save_config()

    async def add_route(self, guild_id, chf, cht):
        # check dup
        routes = await self.config_get(guild_id, 'routes')
        if any([q[0] == chf.id and q[1] == cht.id for q in routes]):
            raise ValueError('Duplicate routes are forbidden')
        # check cycle
        if chf == cht:
            raise BlockingIOError('Loop routes are forbidden')
        # add
        routes.append((chf.id, cht.id))
        # save
        await self.config_set(guild_id, 'routes', routes)

    async def rem_route(self, guild_id, chf, cht):
        if not self.check_config(guild_id):
            await self.error(f'Rem route for {guild_id} with no config present')
            raise EnvironmentError
        routes = await self.config_get(guild_id, 'routes')
        for i in range(routes.__len__()):
            if routes[i][0] == chf.id and routes[i][1] == cht.id:
                routes.pop(i)
                await self.config_set(guild_id, 'routes', routes)
                return
        raise NotFound


    async def add_control(self, guild_id, control):
        controls = await self.config_get(guild_id, 'control')
        if control not in controls:
            controls.append(control)
            l.info(f'CONTROL {control} now has auth for {guild_id}')
        else:
            controls = [q for q in controls if q != control]
            l.info(f'CONTROL {control} now does not have auth for {guild_id}')
        await self.config_set(guild_id, 'control', controls)


    async def rem_route_by_index(self, guild_id, idx):
        if not self.check_config(guild_id):
            await self.error(f'Rem route by index asked for {guild_id} with no config present')
            raise EnvironmentError
        routes = await self.config_get(guild_id, 'routes')
        if idx >= routes.__len__():
            await self.error(f'Requested wrong route rem for {guild_id}')
            raise IndexError
        routes.pop(idx)
        await self.config_set(guild_id, 'routes', routes)

    async def on_ready(self):
        l.info('Curator ready')

    async def on_message(self, message):
        if message.author == self.user:
            return

        if message.type != MessageType.default:
            return

        if message.guild is None or not self.check_config(message.guild.id):
            l.debug(f'No config ready for message from {message.channel.__class__} {message.channel.id}')
            return

        # check command (presuming message default)
        sep = await self.config_get(message.guild.id, 'sep')
        if message.content.startswith(sep):
            if not await self.auth(message.guild, message.author):
                l.warning(f'{message.author} in {message.guild} is being cheeky')
                return
            # command
            command = message.content[sep.__len__():]
            cmd, *content = command.split(' ')
            cmd = cmd.lower()
            # todo change to function dict
            if cmd == 'sep':
                if content.__len__() > 1 or content.__len__() == 0:
                    await self.error(f'Got wrong sep command from {message.guild.name}',
                               notif=f'**Usage**:{await self.config_get(message.guild.id, "sep")}sep *<new_value>*',
                               channel=message.channel)
                    # todo: return false command
                else:
                    await self.config_set(message.guild.id, 'sep', content[0])
                    await self.answer(f'Separator is now {content[0]}', message.channel)
                return

            elif cmd == 'add':
                if content.__len__() != 2:
                    await self.error(f'Got wrong add command from {message.guild.name}', notif='Unknown command',
                               channel=message.channel)
                else:
                    # todo: return failure message
                    if not content[0].startswith('<#') or not content[1].startswith('<#'):
                        await self.error(f'ADD Wrong channel name from {message.guild.name} {content}',
                                   notif=f'**Usage**:{await self.config_get(message.guild.id, "sep")}add '
                                   f'#channel_from #channel_to', channel=message.channel)
                        return
                    try:
                        channel_from = await self.fetch_channel(int(content[0][2:-1]))
                        channel_to = await self.fetch_channel(int(content[1][2:-1]))
                    except ValueError:
                        await self.error(f'Someone\'s being cheeky in {message.guild.name}',
                                   notif=f'{message.author.name} seems to be trying to '
                                   f'break the bot in {message.channel.mention}', guild=message.guild)
                        return
                    except InvalidData:
                        await self.error(f'ADD Unknown channel type receieved, failed for {message.guild.name}',
                                   notif=f'Received invalid data in {message.channel.mention}', guild=message.guild)
                        return
                    except HTTPException:
                        await self.error(f'ADD no channel found (probably permission error?) for {message.guild.name}',
                                   notif='I can\'t, Captain, I need more power!', channel=message.channel)
                        return
                    except (NotFound, Forbidden):
                        await self.error(f'ADD Channel not found or forbidden, failing {message.guild.name}')
                        await self.error(f'ADD GIB PERMISSIONS {message.guild.name}',
                                   notif=f'Gib permissions! {message.channel.mention}', guild=message.guild)
                        return

                    # channel checks
                    if channel_from is None or channel_to is None:
                        await self.error(f'ADD from {message.guild.name} channel {channel_from}:{channel_to} does not exist '
                                   f'or not permitted', notif='I don\'t know those channels', channel=message.channel)
                        return
                    try:
                        await self.add_route(message.guild.id, channel_from, channel_to)  # todo failure messages
                        await self.answer(f'New route added {channel_from.mention}:arrow_forward:{channel_to.mention}',
                                          message.channel)
                    except ValueError:
                        await self.error(f'ADD Duplicate route for {message.guild.name}', notif='No duplicate routes',
                                   channel=message.channel)
                        return
                    except BlockingIOError:
                        await self.error(f'ADD Loop route for {message.guild.name}', notif='No loop routes for now, plz',
                                   channel=message.channel)
                        return
                    l.info(f'ADD route created for {message.guild.name} {channel_from}->{channel_to}')
                return

            elif cmd == 'rem':
                if content.__len__() != 1 and content.__len__() != 2:
                    await self.error(f'Got wrong rem command from {message.guild.name}',
                               notif=f'**Usages**: \n1. {await self.config_get(message.guild.id, "sep")}rem <index>'
                               f'\n2. {await self.config_get(message.guild.id, "sep")}rem #channel_from #channel_to',
                               channel=message.channel)
                else:
                    if content.__len__() == 1:
                        # todo: more exceptional programming everywhere
                        try:
                            await self.rem_route_by_index(message.guild.id, int(content[0]))
                            await self.answer('Route deleted', message.channel)
                            l.info(f'REM deleted route {content[0]}')
                        except ValueError:
                            await self.error(f'REM Wrong number {content[0]} from {message.guild.name}',
                                       notif='This is not a number', channel=message.channel)
                            return
                        except IndexError:
                            await self.error(f'REM index out of bounds {content[0]} from {message.guild.name}',
                                       notif='Not a number\nDo you count from 1? I don\'t.',
                                       channel=message.channel)
                            return
                        except EnvironmentError:
                            await self.error(f'REM very bad, no config', notif=f'Something went horribly wrong in '
                                                                         f'{message.channel.mention}',
                                       guild=message.guild)
                            return
                    else:
                        try:  # todo squish this up
                            try:
                                channel_from = await self.fetch_channel(int(content[0][2:-1]))
                                channel_to = await self.fetch_channel(int(content[1][2:-1]))
                            except ValueError:
                                l.error(f'Someone\'s being cheeky in {message.guild.name}')
                                return  # squishing will fix this horror
                            except InvalidData:
                                l.error(f'ADD Unknown channel type receieved, failed for {message.guild.name}')
                                return
                            except HTTPException:
                                l.error(f'ADD no channel found (probably permission error?) for {message.guild.name}')
                                return
                            except (NotFound, Forbidden):
                                await self.error(f'ADD Channel not found, failing {message.guild.name}',
                                           notif='I don\'t have enough permissions for this',
                                           channel=message.channel)
                                return
                            await self.rem_route(message.guild.id, channel_from, channel_to)
                            l.info(f'REM removed for {message.guild} {channel_from}->{channel_to}')
                            await self.answer('Removed route ok', channel=message.channel)
                        except NotFound:
                            await self.error(f'REM direct route was not found for {message.guild} '
                                       f'{channel_from}->{channel_to}',
                                       notif='Route not found',
                                       channel=message.channel)
                        except EnvironmentError:
                            await self.error(f'REM very bad, no config',
                                       notif=f'Something went horribly wrong in {message.channel.mention}',
                                       guild=message.guild)
                return

            elif cmd == 'show':
                l.debug(f'SHOW building routes')
                routes = await self.config_get(message.guild.id, "routes")
                text = '\n'.join(['{}: <#{}>:arrow_forward:<#{}>'.format(i, q[0], q[1]) for q, i in zip(routes, range(routes.__len__()))])
                if text == '':
                    text = f'No routes have been created.\nStart by using {await self.config_get(message.guild.id, "sep")}add'
                await self.answer(text, message.channel)
                return
            elif cmd == 'control':
                # 'I think we should add <@86890631690977280> to the <@&134362454976102401> role.'
                if content.__len__() > 1:
                    await self.error(f'Set control points one by one please', channel=message.channel)
                    return
                if content.__len__() == 1:
                    content = content[0][3:-1]
                else:
                    content = None
                try:
                    if content is not None:
                        await self.add_control(message.guild.id, int(content))
                        l.info(f'CONTROL {content} auth switch for {message.guild}')
                    authlist = await self.config_get(message.guild.id, 'control')
                    roles = await message.guild.fetch_roles()
                    roles = [q.id for q in roles]
                    mentions = [f'<@&{q}>' if q in roles else f'<@{q}>' for q in authlist]
                    if mentions.__len__() == 0:
                        mentions.append('**Careful**, control list is empty: Anyone can do commands!')
                    if content is not None:
                        await self.notif(f'Auth list have been changed by {message.author.mention}, '
                                         f'now is:\n{", ".join(mentions)}', message.guild)
                    else:
                        await self.answer(f'Auth list is:\n'
                                         f'{", ".join(mentions)}', message.channel)
                except ValueError:
                    l.error(f'Someone is being cheeky in {message.guild}')
                return
            elif cmd == 'text':
                if content.__len__() == 0:
                    text = await self.config_get(message.guild.id, 'content')
                    return await self.answer(f'Repost text is: {text}', message.channel)
                content = ' '.join(content)
                l.info(f'TEXT setting repost content for {message.guild}')
                await self.config_set(message.guild.id, 'content', content)
                await self.answer(f'Repost text is now {content}', message.channel)
                return
            elif cmd == 'help':
                sep = await self.config_get(message.guild.id, 'sep')
                await self.answer(f'Available commands are:\n'
                                  f'{sep}add #channel #channel\n'
                                  f'{sep}rem <index>\n'
                                  f'{sep}rem #channel #channel\n'
                                  f'{sep}show\n'
                                  f'{sep}sep <separator>\n'
                                  f'{sep}text <repost text>\n'
                                  f'{sep}control <group or user>\n'
                                  f'{sep}notif #notification_channel\n'
                                  f'{sep}help\n'
                                  , message.channel)
            elif cmd == 'notif':
                if content.__len__() != 1:
                    return await self.error(f'Wrong notif command in {message.guild}',
                               notif=f'**Usage**: {await self.config_get(message.guild.id, "sep")}notif #channel',
                               channel=message.channel)
                try:
                    ch = await self.fetch_channel(int(content[0][2:-1]))
                    await self.config_set(message.guild.id, 'notification_channel', ch.id)
                    await self.notif('This is the new notification channel', guild=message.guild)
                except ValueError:
                    await self.error(f'Someone\'s being cheeky in {message.guild.name}',
                               notif=f'Someone is trying to break the bot in {message.channel.mention}',
                               guild=message.guild)
                    return  # squishing will fix this horror
                except InvalidData:
                    await self.error(f'NOTIF Unknown channel type receieved, failed for {message.guild.name}',
                               notif='Unknown channel type', channel=message.channel)
                    return
                except HTTPException:
                    await self.error(f'ADD no channel found (probably permission error?) for {message.guild.name}',
                            notif='I just don\'t know what wen wrong',
                            channel=message.channel)
                    return
                except (NotFound, Forbidden):
                    await self.error(f'ADD Channel not found, failing {message.guild.name}',
                               notif='I don\'t have enough permissions for this',
                               channel=message.channel)
                    return

            else:
                await self.error(f'Unknown command from {message.guild.name}', notif='Unknown command',
                           channel=message.channel)
                # todo: wrong command return
                return

        # check routes
        for route in await self.config_get(message.guild.id, 'routes'):
            if message.channel.id == route[0]:
                # todo: more route configurations for media and stuffs
                l.info(f'Route hit for {message.guild.name}, from channel {message.channel.name}')
                if message.attachments.__len__() == 0 and message.embeds.__len__() == 0:
                    l.debug(f'No data to transfer, closing')
                    return
                # send into target
                try:  # todo: make this more user friendly and secure somehow (tags?)
                    text = await self.config_get(message.guild.id, 'content')
                    text = text.format(message.author.name)
                except IndexError:
                    await self.config_set(message.guild.id, 'content', Curator.get_default_config()['content'])
                    text = await self.config_get(message.guild.id, 'content')
                    text = text.format(message.author.name)
                embed = Embed().set_author(name=text, icon_url=message.author.avatar_url)
                embed.title = message.jump_url
                attach = None
                if message.attachments.__len__() > 0:
                    # spoiler if spoilerd
                    if message.attachments[0].is_spoiler():
                        attach = await message.attachments[0].to_file()
                    else:
                        embed = embed.set_image(url=message.attachments[0].url)
                elif message.embeds.__len__() > 0:
                    embed = embed.set_image(url=message.embeds[0].url)
                # thumbnail up if none exist
                if isinstance(embed.image.url, str):
                    replace = embed.image.url
                else:
                    replace = ''
                embed.set_footer(text=message.content.replace(replace, ''))
                l.info(f'Reposting in {message.guild} to {route[1]}')
                try:
                    ch = await self.fetch_channel(route[1])
                    await ch.send(embed=embed, file=attach)
                except InvalidData:
                    l.error(f'Improper route (can\'t send) in {message.guild}, not deleting, check code (invalid data)')
                except (Forbidden, HTTPException, NotFound):
                    l.error(f'Improper route (can\'t send) in {message.guild}, deleting')
                    await self.rem_route(message.guild.id, route[0], route[1])

    async def on_guild_join(self, guild):
        self.add_config(guild.id)

    async def on_guild_remove(self, guild):
        self.remove_config(guild.id)

if __name__ == '__main__':
    client = Curator()
    client.run(TOKEN)