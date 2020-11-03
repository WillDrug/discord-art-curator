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


    def auth(self, guild, user):
        auth = self.config_get(guild.id, 'control')
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
    def config_get(self, guild_id, key):
        if not self.check_config(guild_id):
            l.error(f'Got config get request for {guild_id} which is not present')
            return None
        return self.guild_config[guild_id].get(key)

    def config_set(self, guild_id, key, value):
        if not self.check_config(guild_id):
            l.error(f'Got config set request for {guild_id} which is not present')
        self.guild_config[guild_id][key] = value
        self.save_config()

    def add_route(self, guild_id, chf, cht):
        # check dup
        routes = self.config_get(guild_id, 'routes')
        if any([q[0] == chf.id and q[1] == cht.id for q in routes]):
            raise ValueError('Duplicate routes are forbidden')
        # check cycle
        if chf == cht:
            raise BlockingIOError('Loop routes are forbidden')
        # add
        routes.append((chf.id, cht.id))
        # save
        self.config_set(guild_id, 'routes', routes)

    def rem_route(self, guild_id, chf, cht):
        if not self.check_config(guild_id):
            l.error(f'Rem route for {guild_id} with no config present')
            raise EnvironmentError
        routes = self.config_get(guild_id, 'routes')
        for i in range(routes.__len__()):
            if routes[i][0] == chf.id and routes[i][1] == cht.id:
                routes.pop(i)
                self.config_set(guild_id, 'routes', routes)
                return
        raise NotFound


    def add_control(self, guild_id, control):
        controls = self.config_get(guild_id, 'control')
        if control not in controls:
            controls.append(control)
            l.info(f'CONTROL {control} now has auth for {guild_id}')
        else:
            controls = [q for q in controls if q != control]
            l.info(f'CONTROL {control} now does not have auth for {guild_id}')
        self.config_set(guild_id, 'control', controls)


    def rem_route_by_index(self, guild_id, idx):
        if not self.check_config(guild_id):
            l.error(f'Rem route by index asked for {guild_id} with no config present')
            raise EnvironmentError
        routes = self.config_get(guild_id, 'routes')
        if idx >= routes.__len__():
            l.error(f'Requested wrong route rem for {guild_id}')
            raise IndexError
        routes.pop(idx)
        self.config_set(guild_id, 'routes', routes)

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
        sep = self.config_get(message.guild.id, 'sep')
        if message.content.startswith(sep):
            if not self.auth(message.guild, message.author):
                l.warning(f'{message.author} in {message.guild} is being cheeky')
                return
            # command
            command = message.content[sep.__len__():]
            cmd, *content = command.split(' ')
            cmd = cmd.lower()
            # todo change to function dict
            if cmd == 'sep':
                if content.__len__() > 1 or content.__len__() == 0:
                    l.error(f'Got wrong sep command from {message.guild.name}')
                    # todo: return false command
                else:
                    self.config_set(message.guild.id, 'sep', content[0])
                return

            elif cmd == 'add':
                if content.__len__() != 2:
                    l.error(f'Got wrong add command from {message.guild.name}')
                else:
                    # todo: return failure message
                    if not content[0].startswith('<#') or not content[1].startswith('<#'):
                        l.error(f'ADD Wrong channel name from {message.guild.name} {content}')
                        return
                    try:
                        channel_from = await self.fetch_channel(int(content[0][2:-1]))
                        channel_to = await self.fetch_channel(int(content[1][2:-1]))
                    except ValueError:
                        l.error(f'Someone\'s being cheeky in {message.guild.name}')
                        return
                    except InvalidData:
                        l.error(f'ADD Unknown channel type receieved, failed for {message.guild.name}')
                        return
                    except HTTPException:
                        l.error(f'ADD no channel found (probably permission error?) for {message.guild.name}')
                        return
                    except NotFound:
                        l.error(f'ADD Channel not found, failing {message.guild.name}')
                        return
                    except Forbidden:
                        l.error(f'ADD GIB PERMISSIONS {message.guild.name}')
                        return

                    # channel checks
                    if channel_from is None or channel_to is None:
                        l.error(f'ADD from {message.guild.name} channel {channel_from}:{channel_to} does not exist or not permitted')
                        return
                    try:
                        self.add_route(message.guild.id, channel_from, channel_to)  # todo failure messages
                    except ValueError:
                        l.error(f'ADD Duplicate route for {message.guild.name}')
                        return
                    except BlockingIOError:
                        l.error(f'ADD Loop route for {message.guild.name}')
                        return
                    l.info(f'ADD route created for {message.guild.name} {channel_from}->{channel_to}')
                return

            elif cmd == 'rem':
                if content.__len__() != 1 and content.__len__() != 2:
                    l.error(f'Got wrong rem command from {message.guild.name}')
                else:
                    if content.__len__() == 1:
                        # todo: more exceptional programming everywhere
                        try:
                            self.rem_route_by_index(message.guild.id, int(content[0]))
                            l.info(f'REM deleted route {content[0]}')
                        except ValueError:
                            l.error(f'REM Wrong number {content[0]} from {message.guild.name}')
                            # todo error msg
                            return
                        except IndexError:
                            l.error(f'REM index out of bounds {content[0]} from {message.guild.name}')
                            # todo error msg
                            return
                        except EnvironmentError:
                            l.error(f'REM very bad, no config')
                            # todo error msg
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
                            except NotFound:
                                l.error(f'ADD Channel not found, failing {message.guild.name}')
                                return
                            except Forbidden:
                                l.error(f'ADD GIB PERMISSIONS {message.guild.name}')
                                return
                            self.rem_route(message.guild.id, channel_from, channel_to)
                            l.info(f'REM removed for {message.guild} {channel_from}->{channel_to}')
                        except NotFound:
                            l.error(f'REM direct route was not found for {message.guild} {channel_from}->{channel_to}')
                        except EnvironmentError:
                            l.error(f'REM very bad, no config')
                            # todo error msg
                return

            elif cmd == 'show':
                l.debug(f'{self.config_get(message.guild.id, "routes")}')
                return
            elif cmd == 'control':
                # 'I think we should add <@86890631690977280> to the <@&134362454976102401> role.'
                if content.__len__() != 1:
                    l.error(f'Set control points one by one please')  # todo error msg
                    return
                content = content[0][3:-1]
                try:
                    self.add_control(message.guild.id, int(content))
                    l.info(f'CONTROL {content} auth switch for {message.guild}')
                except ValueError:
                    l.error(f'Someone is being cheeky in {message.guild}')
                return
            elif cmd == 'text':
                content = ' '.join(content)
                l.info(f'TEXT setting repost content for {message.guild}')
                self.config_set(message.guild.id, 'content', content)
                return
            else:
                l.error(f'Unknown command from {message.guild.name}')
                # todo: wrong command return
                return

        # check routes
        for route in self.config_get(message.guild.id, 'routes'):
            if message.channel.id == route[0]:
                # todo: more route configurations for media and stuffs
                l.info(f'Route hit for {message.guild.name}, from channel {message.channel.name}')
                if message.attachments.__len__() == 0 and message.embeds.__len__() == 0:
                    l.debug(f'No data to transfer, closing')
                    return
                # send into target
                embed = Embed().set_author(name=self.config_get(message.guild.id, 'content').format(message.author.name), icon_url=message.author.avatar_url)
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
                    self.rem_route(message.guild.id, route[0], route[1])

    async def on_guild_join(self, guild):
        self.add_config(guild.id)

    async def on_guild_remove(self, guild):
        self.remove_config(guild.id)

if __name__ == '__main__':
    client = Curator()
    client.run(TOKEN)