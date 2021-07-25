#!venv/bin/python
import argparse
import asyncio
import logging
import os
import re
import signal
import traceback

import aiomysql
import discord
import dotenv
from discord.ext import commands

dotenv.load_dotenv()
argparser = argparse.ArgumentParser(description='Launch Jolteon discord bot')
argparser.add_argument('--loglevel', help='Set the logging level of Jolteon', dest='logginglevel', default='INFO')
argparser.add_argument('--logfile', help='Set the file for Jolteon to log to', dest='loggingfile',
                       default='jolteon.log')
argparser.add_argument('--status', help='Set Jolteon\'s status ', dest='botstatus', default=os.getenv('status'))
argparser.add_argument('--activity', help='Set Jolteon\'s activity', dest='botactivity', default=os.getenv('activity'))
flags, wrongflags = argparser.parse_known_args()
logginglevel = getattr(logging, flags.logginglevel.upper())
if flags.botstatus:
    botstatus = getattr(discord.Status, flags.botstatus.lower())
else:
    botstatus = discord.Status.online
if flags.botactivity:
    botactivity = discord.Activity(type=getattr(discord.ActivityType, flags.botactivity.split()[0].lower()), name=flags.botactivity.split(' ', 1)[1])
else:
    botactivity = None

logging.basicConfig(level=logginglevel, filename=flags.loggingfile, filemode='w+')
if wrongflags:
    logging.warning("An unrecognised flag was passed, skipping")
logging.info("Starting Jolteon.....")


async def prefixgetter(bot, message):
    # set default prefix
    default_prefix = ";"
    # list of pings so that they can be used as prefixes
    ping_prefixes = [bot.user.mention, bot.user.mention.replace('@', '@!')]
    # try to get the guild id. if there isn't one, then it's a DM and uses the default prefix.
    try:
        guildid = message.guild.id
    except AttributeError:
        return default_prefix
    connection = await bot.sql_server_pool.acquire()
    db = await connection.cursor()
    # find which prefix matches this specific server id
    await db.execute(f'''SELECT prefix FROM prefixes WHERE guildid = %s''', (guildid,))
    # fetch the prefix
    custom_prefix = await db.fetchone()
    # if the custom prefix exists, then send it back, otherwise return the default one
    await db.close()
    connection.close()
    bot.sql_server_pool.release(connection)
    if custom_prefix:
        return str(custom_prefix[0]), *ping_prefixes
    else:
        return default_prefix, *ping_prefixes


class Help(commands.MinimalHelpCommand):
    # actually sends the help
    # noinspection PyTypeChecker
    async def send_bot_help(self, mapping):
        embed = discord.Embed(colour=jolteon.embedcolor, title="Help")
        prefix = await prefixgetter(jolteon, self.context.message)
        embed.add_field(name="Tags",
                        value=f"You can use the tags by using `{prefix[0]}t <tag> [@mention]`\n\n[List of tags](https://glaceon.xyz/jolteon/{self.context.guild.id}) \n\n You can delete a tag by reacting with the 🗑️ emoji",
                        inline=False)
        prefix = await prefixgetter(jolteon, self.context.message)
        embed.add_field(name="Prefix", value=f"`{prefix[0]}` or <@{self.context.me.id}>", inline=False)
        await self.get_destination().send(embed=embed)


# Sets the discord intents to all
intents = discord.Intents().all()
# defines the glaceon class as a bot with the prefixgetter prefix and case-insensitive commands
logging.info("Initializing bot!")
jolteon = commands.Bot(command_prefix=prefixgetter, case_insensitive=True, intents=intents,
                       help_command=Help(command_attrs={'aliases': ['man']}),
                       activity=botactivity,
                       status=botstatus,
                       strip_after_prefix=True)
jolteon.embedcolor = 0xadd8e6
logging.info("Connecting to SQL server!")


async def connect_to_sql():
    conn = await aiomysql.create_pool(host=os.getenv('SQLserverhost'),
                                      user=os.getenv('SQLusername'),
                                      password=os.getenv('SQLpassword'),
                                      db=os.getenv('SQLdatabase'),
                                      autocommit=True,
                                      maxsize=10,
                                      minsize=1)
    return conn


loop = asyncio.get_event_loop()
jolteon.sql_server_pool = loop.run_until_complete(connect_to_sql())
logging.debug(f"Connected to sql server {os.getenv('SQLserverhost')} as {os.getenv('SQLusername')} "
              f"on database {os.getenv('SQLdatabase')}, max connections {jolteon.sql_server_pool.maxsize}")


async def if_wastebasket_reacted(ctx, reply):
    def added_emoji_check(reaction, user):  # the actual check
        return user == ctx.message.author and str(reaction.emoji) == '🗑️'

    reaction, user = await jolteon.wait_for('reaction_add', check=added_emoji_check)
    try:
        await reply.delete()
    except discord.NotFound:
        pass


@jolteon.command(aliases=["t"])
@commands.guild_only()
async def tag(ctx, *inputs):
    """Call a tag. (or two, or ten)"""
    for each_input in inputs:
        if "@everyone" in each_input or "@here" in each_input:
            await ctx.reply("Mass ping attempt detected, no actions taken.")
            return
    if ctx.message.role_mentions:
        await ctx.reply("Role mention attempt detected, no actions taken")
        return
    else:
        errors = False
        factoids = []
        pings = []
        for user in ctx.message.mentions:
            pings.append(user.mention)
        sid = ctx.guild.id
        tags = [tag for tag in inputs if not re.match(r'<@(!?)([0-9]*)>', tag)]
        async with jolteon.sql_server_pool.acquire() as connection:
            async with connection.cursor() as db:
                for t in tags:
                    t = t.lower()
                    if t == "help":
                        factoids.append(f"You can use the tags by using `{prefix[0]}t <tag> [@mention]`\n\n[List of tags](https://glaceon.xyz/jolteon/{ctx.guild.id}) \n\nYou can delete a tag by reacting with the 🗑️ emoji")
                    await db.execute('''SELECT tagcontent FROM tags WHERE guildid = %s AND tagname = %s''', (sid, t))
                    factoid = await db.fetchone()
                    await db.close()
                    if factoid:
                        if factoid != "help":
                            factoids.append(factoid[0])
                    else:
                        await ctx.send(f"tag `{t}` not found!", delete_after=15)
                        errors = True
                        break
                if errors is False:
                    if factoids:
                        if len("\n\n".join(factoids)) >= 4096:
                            await ctx.reply("You have too many factoids!")
                            return
                        await ctx.message.delete()
                        embed = discord.Embed(colour=jolteon.embedcolor, description="\n\n".join(factoids))
                        embed.set_footer(text=f"I am a bot, i will not respond to you | Request by {ctx.author}")
                        our_message = await ctx.send(" ".join(pings) + " Please refer to the below information.", embed=embed)
                        wastebasket_check_task = asyncio.create_task(if_wastebasket_reacted(ctx, our_message))
                        await wastebasket_check_task
                    else:
                        await ctx.reply("You need to specify a tag!", delete_after=15)


@jolteon.command(aliases=["tmanage", "tagmanage", "tadd", "tm", "ta"])
@commands.has_guild_permissions(manage_messages=True)
@commands.guild_only()
async def tagadd(ctx, name, *, contents):
    """add or edit tags"""
    if len(contents) > 1900:
        await ctx.reply("That factoid is too long!")
    elif re.match(r'<@(!?)([0-9]*)>', name):
        await ctx.reply("You cannot have a ping factoid.")
    else:
        async with jolteon.sql_server_pool.acquire() as connection:
            async with connection.cursor() as db:
                await db.execute(f'''SELECT guildid FROM tags WHERE guildid = %s AND tagname = %s''',
                                 (ctx.guild.id, name.lower()))
                if await db.fetchone():
                    await db.execute('''UPDATE tags SET tagcontent = %s WHERE guildid = %s AND tagname = %s''',
                                     (contents, ctx.guild.id, name.lower()))
                else:
                    await db.execute('''INSERT INTO tags(guildid, tagname, tagcontent) VALUES (%s,%s,%s)''',
                                     (ctx.guild.id, name.lower(), contents))
                await ctx.reply(f"Tag added with name `{name.lower()}` and contents `{contents}`")


@jolteon.command(aliases=["trm", "tagremove"])
@commands.has_guild_permissions(manage_messages=True)
@commands.guild_only()
async def tagdelete(ctx, name):
    """Remove a tag"""
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass
    async with jolteon.sql_server_pool.acquire() as connection:
        async with connection.cursor() as db:
            await db.execute('''DELETE FROM tags WHERE guildid = %s AND tagname = %s''', (ctx.guild.id, name.lower()))
    await ctx.reply(f"tag `{name.lower()}` deleted", delete_after=10)


@jolteon.command()
@commands.has_guild_permissions(administrator=True)  # requires that the person issuing the command has administrator
@commands.guild_only()
async def prefix(ctx, newprefix):  # context and what we should set the new prefix to
    """Sets the bot prefix for this server"""
    async with jolteon.sql_server_pool.acquire() as connection:
        async with connection.cursor() as db:
            await db.execute(f'''SELECT prefix FROM prefixes WHERE guildid = %s''',
                             (ctx.guild.id,))  # get the current prefix for that server, if it exists
            if await db.fetchone():  # actually check if it exists
                await db.execute('''UPDATE prefixes SET prefix = %s WHERE guildid = %s''',
                                 (newprefix, ctx.guild.id))  # update prefix
            else:
                await db.execute("INSERT INTO prefixes(guildid, prefix) VALUES (%s,%s)",
                                 (ctx.guild.id, newprefix))  # set new prefix
    # close connection
    await ctx.send(f"Prefix set to {newprefix}")  # tell admin what happened


# on_message custom command handler
@jolteon.event
async def on_message(message):
    ctx = await jolteon.get_context(message)
    if message.content.startswith(await prefixgetter(jolteon, message)):
      pass #someday this will be the custom log checker
    await jolteon.process_commands(message)

@jolteon.event
async def on_command_error(ctx, error):
    if hasattr(ctx.command, 'on_error'):
        # await ctx.message.add_reaction('<:CommandError:804193351758381086>')
        return

    elif isinstance(error, discord.ext.commands.errors.CommandNotFound) or ctx.command.hidden:
        return

    elif isinstance(error, discord.ext.commands.errors.NotOwner):
        await ctx.reply("Only bot administrators can do that.")
        return

    elif isinstance(error, discord.ext.commands.errors.MissingPermissions):
        await ctx.reply("You are not allowed to do that!")
        return

    elif isinstance(error, discord.ext.commands.errors.BotMissingPermissions):
        try:
            await ctx.reply("I do not have the requisite permissions to do that!")
        except discord.Forbidden:
            pass
        return

    elif isinstance(error, discord.ext.commands.errors.MissingRole):
        await ctx.reply("I am missing the role to do that!")
        return

    elif isinstance(error, discord.ext.commands.errors.CommandOnCooldown):
        if str(error.cooldown.type.name) != "default":
            cooldowntype = f'per {error.cooldown.type.name}'

        else:
            cooldowntype = 'global'
        await ctx.reply(
            f"This command is on a {round(error.cooldown.per, 0)} second {cooldowntype} cooldown.\n"
            f"Wait {round(error.retry_after, 1)} seconds, and try again.",
            delete_after=min(10, error.retry_after))
        return

    elif isinstance(error, discord.ext.commands.errors.MissingRequiredArgument):
        await ctx.reply(f"Missing required argument!\nUsage:`{ctx.command.signature}`", delete_after=30)
        return

    elif isinstance(error, discord.ext.commands.errors.BadArgument):
        await ctx.reply(f"Invalid argument!\nUsage:`{ctx.command.signature}`", delete_after=30)
        return

    elif isinstance(error, discord.ext.commands.errors.NoPrivateMessage):
        await ctx.reply("That can only be used in servers, not DMs!")
        return

    else:
        # Send user a message
        # get data from exception

        etype = type(error)
        trace = error.__traceback__

        # 'traceback' is the stdlib module, `import traceback`.
        lines = traceback.format_exception(etype, error, trace)

        traceback_text = ''.join(lines)
        n = 1988
        chunks = [traceback_text[i:i + n] for i in range(0, len(traceback_text), n)]
        # now we can send it to the us
        bug_channel = jolteon.get_channel(int(os.getenv('ErrorChannel')))
        for traceback_part in chunks:
            await bug_channel.send("```\n" + traceback_part + "\n```")
        await bug_channel.send(" Command being invoked: " + ctx.command.name)
        await ctx.send("Error!\n```" + str(
            error) + "```\nvalkyrie_pilot will be informed.  Most likely this is a bug, but check your syntax.",
                       delete_after=30)


logging.info('Running bot....')
jolteon.run(os.getenv('bot_token'))
