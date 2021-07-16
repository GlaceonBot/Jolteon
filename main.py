import asyncio
import os
import re
import traceback

import dotenv
import aiomysql
import discord
from discord.ext import commands

dotenv.load_dotenv()


async def prefixgetter(jolteon, message):
    # set default prefix
    default_prefix = ";"
    # list of pings so that they can be used as prefixes
    ping_prefixes = [jolteon.user.mention, jolteon.user.mention.replace('@', '@!')]
    # try to get the guild id. if there isn't one, then it's a DM and uses the default prefix.
    try:
        guildid = message.guild.id
    except AttributeError:
        return default_prefix
    connection = await jolteon.sql_server_pool.acquire()
    db = await connection.cursor()
    # find which prefix matches this specific server id
    await db.execute(f'''SELECT prefix FROM prefixes WHERE guildid = %s''', (guildid,))
    # fetch the prefix
    custom_prefix = await db.fetchone()
    # if the custom prefix exists, then send it back, otherwise return the default one
    await db.close()
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
        embed.add_field(name="Commands",
                        value=f"You can use the tags by using `{prefix[0]}t <tag> [@mention]`\n\nYou can get a list of tags by running `{prefix[0]}tl`",
                        inline=False)
        prefix = await prefixgetter(jolteon, self.context.message)
        embed.add_field(name="Prefix", value=f"`{prefix[0]}` or <@{self.context.me.id}>", inline=False)
        await self.get_destination().send(embed=embed)


# Sets the discord intents to all
intents = discord.Intents().all()
# defines the glaceon class as a bot with the prefixgetter prefix and case-insensitive commands
jolteon = commands.Bot(command_prefix=prefixgetter, case_insensitive=True, intents=intents,
                       help_command=Help(command_attrs={'aliases': ['man']}),
                       activity=discord.Activity(type=discord.ActivityType.watching, name="out for you"),
                       status=discord.Status.do_not_disturb,
                       strip_after_prefix=True)
jolteon.embedcolor = 0xadd8e6


async def connect_to_sql_server():
    sql_server_connection = await aiomysql.create_pool(host=os.getenv('SQLserverhost'),
                                                       user=os.getenv('SQLusername'),
                                                       password=os.getenv('SQLpassword'),
                                                       db=os.getenv('SQLdatabase'),
                                                       autocommit=True)
    return sql_server_connection


loop = asyncio.get_event_loop()
jolteon.sql_server_pool = loop.run_until_complete(connect_to_sql_server())


@jolteon.command(aliases=["t"])
@commands.guild_only()
async def tag(self, ctx, *inputs):
    """Call a tag. (or two, or ten)"""
    await ctx.message.delete()
    for each_input in inputs:
        if "@everyone" in each_input or "@here" in each_input:
            await ctx.send("Mass ping attempt detected, no actions taken.")
            return
    if ctx.message.role_mentions:
        await ctx.send("Role mention attempt detected, no actions taken")
    else:
        errors = False
        factoids = []
        pings = []
        for user in ctx.message.mentions:
            pings.append(user.mention)
        sid = ctx.guild.id
        tags = [tag for tag in inputs if not re.match(r'<@(!?)([0-9]*)>', tag)]
        for t in tags:
            t = t.lower()
            connection = await jolteon.sql_server_pool.acquire()
            db = await connection.cursor()
            await db.execute('''SELECT tagcontent FROM tags WHERE guildid = %s AND tagname = %s''', (sid, t))
            factoid = await db.fetchone()
            await db.close()
            if factoid:
                factoids.append(factoid[0])
            else:
                await ctx.send(f"tag `{t}` not found!", delete_after=15)
                errors = True
                break
        if errors is False:
            if factoids:
                embed = discord.Embed(colour=self.glaceon.embedcolor, description="\n\n".join(factoids))
                embed.set_footer(text=f"I am a bot, i will not respond to you | Request by {ctx.author}")
                await ctx.send(" ".join(pings) + " Please refer to the below information.", embed=embed)
            else:
                await ctx.send("You need to specify a tag!", delete_after=15)


@jolteon.command(aliases=["tmanage", "tagmanage", "tadd", "tm", "ta"])
@commands.has_guild_permissions(manage_messages=True)
@commands.guild_only()
async def tagadd(ctx, name, *, contents):
    """add or edit tags"""
    await ctx.message.delete()
    connection = await jolteon.sql_server_pool.acquire()
    db = await connection.cursor()
    if len(contents) > 1900:
        await ctx.send("That factoid is too long!")
    else:
        await db.execute(f'''SELECT guildid FROM tags WHERE guildid = %s AND tagname = %s''',
                         (ctx.guild.id, name.lower()))
        if await db.fetchone():
            await db.execute('''UPDATE tags SET tagcontent = %s WHERE guildid = %s AND tagname = %s''',
                             (contents, ctx.guild.id, name.lower()))
        else:
            await db.execute('''INSERT INTO tags(guildid, tagname, tagcontent) VALUES (%s,%s,%s)''',
                             (ctx.guild.id, name.lower(), contents))
        await db.close()
        await ctx.send(f"Tag added with name `{name.lower()}` and contents `{contents}`", delete_after=10)


@jolteon.command(aliases=["trm", "tagremove"])
@commands.has_guild_permissions(manage_messages=True)
@commands.guild_only()
async def tagdelete(ctx, name):
    """Remove a tag"""
    await ctx.message.delete()
    connection = await jolteon.sql_server_pool.acquire()
    db = await connection.cursor()
    await db.execute('''DELETE FROM tags WHERE guildid = %s AND tagname = %s''', (ctx.guild.id, name.lower()))
    await db.close()
    await ctx.send(f"tag `{name.lower()}` deleted", delete_after=10)



@jolteon.command(aliases=["tlist", "tl", "taglist"])
@commands.guild_only()
async def tagslist(ctx):
    """list the tags on this server"""
    await ctx.message.delete()
    sid = ctx.guild.id
    connection = await jolteon.sql_server_pool.acquire()
    db = await connection.cursor()
    await db.execute('''SELECT tagname FROM tags WHERE guildid = %s''', (sid,))
    factoids = await db.fetchall()
    await db.close()
    if factoids:
        await ctx.send('`' + "`, `".join([i for (i,) in factoids]) + '`')
    else:
        await ctx.send(f"This guild has no tags!")


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


jolteon.run(os.getenv('bot_token'))
