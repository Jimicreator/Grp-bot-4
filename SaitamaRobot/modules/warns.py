import html
import time
import re
from typing import Optional, List

import telegram
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ParseMode, User, CallbackQuery
from telegram import Message, Chat, Update, Bot
from telegram.error import BadRequest
from telegram.ext import CommandHandler, run_async, DispatcherHandlerStop, MessageHandler, Filters, CallbackQueryHandler
from telegram.utils.helpers import mention_html, escape_markdown

from SaitamaRobot import dispatcher, BAN_STICKER, OWNER_ID, REDIS
from SaitamaRobot.modules.disable import DisableAbleCommandHandler
from SaitamaRobot.modules.helper_funcs.chat_status import is_user_admin, bot_admin, user_admin_no_reply, user_admin, \
    can_restrict, can_delete,  is_user_ban_protected, user_can_ban
from SaitamaRobot.modules.helper_funcs.extraction import extract_text, extract_user_and_text, extract_user
from SaitamaRobot.modules.helper_funcs.filters import CustomFilters
from SaitamaRobot.modules.helper_funcs.misc import split_message
from SaitamaRobot.modules.helper_funcs.string_handling import split_quotes
from SaitamaRobot.modules.log_channel import loggable
from SaitamaRobot.modules.sql import warns_sql as sql
from SaitamaRobot.modules.connection import connected
#from SaitamaRobot.modules.sql.approve_sql import is_approved

from SaitamaRobot.modules.languages import tl
from SaitamaRobot.modules.helper_funcs.alternate import send_message, send_message_raw

WARN_HANDLER_GROUP = 9


# Not async
def warn(bot, user: User, chat: Chat, reason: str, message: Message, warner: User = None, conn=False, delete=False) -> str:
    if is_user_admin(chat, user.id):
        return ""
    

    if warner:
        warner_tag = mention_html(warner.id, warner.first_name)
    else:
        warner_tag = tl(chat.id, "Automatic warning filter.")

    limit, soft_warn, warn_mode = sql.get_warn_setting(chat.id)
    num_warns, reasons = sql.warn_user(user.id, chat.id, reason)
    if num_warns >= limit:
        sql.reset_warns(user.id, chat.id)
        if not soft_warn:
            if not warn_mode:
                chat.unban_member(user.id)
                reply = tl(chat.id, "{} warning, {} has been kicked out!").format(limit, mention_html(user.id, user.first_name))
            elif warn_mode == 1:
                chat.unban_member(user.id)
                reply = tl(chat.id, "{} warning, {} has been kicked!").format(limit, mention_html(user.id, user.first_name))
            elif warn_mode == 2:
                chat.kick_member(user.id)
                reply = tl(chat.id, "{} warning, {} has been blocked!").format(limit, mention_html(user.id, user.first_name))
            elif warn_mode == 3:
                message.bot.restrict_chat_member(chat.id, user.id, can_send_messages=False)
                reply = tl(chat.id, "{} warning, {} has been muted!").format(limit, mention_html(user.id, user.first_name))
        else:
            chat.kick_member(user.id)
            reply = tl(chat.id, "{} warning, {} has been blocked!").format(limit, mention_html(user.id, user.first_name))
            
        for warn_reason in reasons:
            reply += "\n - {}".format(html.escape(warn_reason))

        message.bot.send_sticker(chat.id, BAN_STICKER)  # banhammer marie sticker
        keyboard = None
        log_reason = "<b>{}:</b>" \
                     "\n#WARN_BAN" \
                     "\n<b>Admin:</b> {}" \
                     "\n<b>User:</b> {} (<code>{}</code>)" \
                     "\n<b>Reason:</b> {}"\
                     "\n<b>Counts:</b> <code>{}/{}</code>".format(html.escape(chat.title),
                                                                  warner_tag,
                                                                  mention_html(user.id, user.first_name),
                                                                  user.id, reason, num_warns, limit)

    else:
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton(tl(chat.id, "Remove warning"), callback_data="rm_warn({})".format(user.id)), InlineKeyboardButton(tl(chat.id, "Rules"), url="t.me/{}?start={}".format(dispatcher.bot.username, chat.id))]])

        if num_warns+1 == limit:
            if not warn_mode:
                action_mode = tl(chat.id, "kick")
            elif warn_mode == 1:
                action_mode = tl(chat.id, "kick")
            elif warn_mode == 2:
                action_mode = tl(chat.id, "block")
            elif warn_mode == 3:
                action_mode = tl(chat.id, "Screw feeling")
            reply = tl(chat.id, "{} have a {}/ {} warning ... If you are warned again you will be on {}!").format(mention_html(user.id, user.first_name), num_warns, limit, action_mode)
        else:
            reply = tl(chat.id, "{} have {}/{} warning ... Be carefull!").format(mention_html(user.id, user.first_name), num_warns, limit)
        if reason:
            reply += tl(chat.id, "\n A reason for the last warning:\n{}").format(html.escape(reason))

        log_reason = "<b>{}:</b>" \
                     "\n#WARN" \
                     "\n<b>Admin:</b> {}" \
                     "\n<b>User:</b> {} (<code>{}</code>)" \
                     "\n<b>Reason:</b> {}"\
                     "\n<b>Counts:</b> <code>{}/{}</code>".format(html.escape(chat.title),
                                                                  warner_tag,
                                                                  mention_html(user.id, user.first_name),
                                                                  user.id, reason, num_warns, limit)

    try:
        if delete:
            bot.send_message(
                chat.id, reply, reply_markup=keyboard, parse_mode=ParseMode.HTML
            )
        else:
            message.reply_text(reply, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    except:
        bot.send_message(
                chat.id, reply, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    return log_reason


@run_async
@user_admin_no_reply
@bot_admin
@loggable
def button(update, context):
    query = update.callback_query  # type: Optional[CallbackQuery]
    user = update.effective_user  # type: Optional[User]
    match = re.match(r"rm_warn\((.+?)\)", query.data)
    if match:
        user_id = match.group(1)
        chat = update.effective_chat  # type: Optional[Chat]
        res = sql.remove_warn(user_id, chat.id)
        if res:
            update.effective_message.edit_text(
                tl(update.effective_message, "Warn deleted by {}.").format(mention_html(user.id, user.first_name)),
                parse_mode=ParseMode.HTML)
            user_member = chat.get_member(user_id)
            return "<b>{}:</b>" \
                   "\n#UNWARN" \
                   "\n<b>Admin:</b> {}" \
                   "\n<b>User:</b> {} (<code>{}</code>)".format(html.escape(chat.title),
                                                                mention_html(user.id, user.first_name),
                                                                mention_html(user_member.user.id, user_member.user.first_name),
                                                                user_member.user.id)
        else:
            update.effective_message.edit_text(
            tl(update.effective_message, "The user has no warnings.").format(mention_html(user.id, user.first_name)),
            parse_mode=ParseMode.HTML)
            
    return ""


@run_async
#@spamcheck
@user_admin
#@user_can_banner
@bot_admin
@user_can_ban
@loggable
def warn_user(update, context):
    message = update.effective_message  # type: Optional[Message]
    chat = update.effective_chat  # type: Optional[Chat]
    warner = update.effective_user  # type: Optional[User]
    user = update.effective_user
    args = context.args
    bot = context.bot
    delete = False
    user_id, reason = extract_user_and_text(message, args)
    
        
    if user_id == "error":
        send_message(update.effective_message, tl(update.effective_message, reason))
        return ""

    conn = connected(context.bot, update, chat, user.id, need_admin=True)
    if conn:
        chat = dispatcher.bot.getChat(conn)
        chat_id = conn
        chat_name = dispatcher.bot.getChat(conn).title
    else:
        if update.effective_message.chat.type == "private":
            send_message(update.effective_message, tl(update.effective_message, "You can do this command in a group, not in PM"))
            return ""
        chat = update.effective_chat
        chat_id = update.effective_chat.id
        chat_name = update.effective_message.chat.title

    check = context.bot.getChatMember(chat_id, context.bot.id)
    if check.status == 'member' or check['can_restrict_members'] == False:
        if conn:
            text = tl(update.effective_message, "I can't limit people in {}! Make sure I'm already an admin.").format(chat_name)
        else:
            text = tl(update.effective_message, "I can't limit people here! Make sure I'm already an admin.")
        send_message(update.effective_message, text, parse_mode="markdown")
        return ""
    if message.text.startswith("/d") and message.reply_to_message:
        message.reply_to_message.delete()
        delete = True
    if user_id:
        if conn:
            warning = warn(chat.get_member(user_id).user, chat, reason, message, warner, conn=True)
            send_message(update.effective_message, tl(update.effective_message, "I warned the group *{}*").format(chat_name), parse_mode="markdown")
            return warning
        else:
            if message.reply_to_message and message.reply_to_message.from_user.id == user_id:
                return warn(bot, message.reply_to_message.from_user, chat, reason, message.reply_to_message, warner, delete)
            else:
                return warn(chat.get_member(bot, user_id).user, chat, reason, message, warner, delete)
    else:
        send_message(update.effective_message, tl(update.effective_message, "No user appointed!"))
    return ""

@run_async
#@spamcheck
@user_admin
@user_can_ban
@bot_admin
@loggable
def reset_warns(update, context):
    message = update.effective_message  # type: Optional[Message]
    chat = update.effective_chat  # type: Optional[Chat]
    user = update.effective_user  # type: Optional[User]
    args = context.args

    user_id = extract_user(message, args)

    conn = connected(context.bot, update, chat, user.id, need_admin=True)
    if conn:
        chat = dispatcher.bot.getChat(conn)
        chat_id = conn
        chat_name = dispatcher.bot.getChat(conn).title
    else:
        if update.effective_message.chat.type == "private":
            send_message(update.effective_message, tl(update.effective_message, "You can do this command in the group, not the PM"))
            return ""
        chat = update.effective_chat
        chat_id = update.effective_chat.id
        chat_name = update.effective_message.chat.title

    check = context.bot.getChatMember(chat_id, context.bot.id)
    if check.status == 'member' or check['can_restrict_members'] == False:
        if conn:
            text = tl(update.effective_message, "I can't limit people in {}! Make sure I'm already an admin.").format(chat_name)
        else:
            text = tl(update.effective_message, "I can't limit people here! Make sure I'm already an admin.")
        send_message(update.effective_message, text, parse_mode="markdown")
        return ""
    
    if user_id and user_id != "error":
        sql.reset_warns(user_id, chat.id)
        if conn:
            send_message(update.effective_message, tl(update.effective_message, "The warning has been reset on *{}*!").format(chat_name), parse_mode="markdown")
        else:
            send_message(update.effective_message, tl(update.effective_message, "Warning has been reset!"))
        warned = chat.get_member(user_id).user
        return "<b>{}:</b>" \
               "\n#RESETWARNS" \
               "\n<b>Admin:</b> {}" \
               "\n<b>User:</b> {} (<code>{}</code>)".format(html.escape(chat.title),
                                                            mention_html(user.id, user.first_name),
                                                            mention_html(warned.id, warned.first_name),
                                                            warned.id)
    else:
        send_message(update.effective_message, tl(update.effective_message, "No user specified!"))
    return ""


@run_async
#@spamcheck
def warns(update, context):
    message = update.effective_message  # type: Optional[Message]
    chat = update.effective_chat  # type: Optional[Chat]
    user = update.effective_user  # type: Optional[User]
    args = context.args

    conn = connected(context.bot, update, chat, user.id, need_admin=False)
    if conn:
        chat = dispatcher.bot.getChat(conn)
        chat_id = conn
        chat_name = dispatcher.bot.getChat(conn).title
    else:
        if update.effective_message.chat.type == "private":
            send_message(update.effective_message, tl(update.effective_message, "You can do this command in the group, not the PM"))
            return ""
        chat = update.effective_chat
        chat_id = update.effective_chat.id
        chat_name = update.effective_message.chat.title

    user_id = extract_user(message, args) or update.effective_user.id
    result = sql.get_warns(user_id, chat.id)

    if result and result[0] != 0:
        num_warns, reasons = result
        limit, soft_warn, warn_mode = sql.get_warn_setting(chat.id)

        if reasons:
            if conn:
                text = tl(update.effective_message, "This user has {}/{} warning at *{}*, for the following reason:").format(num_warns, limit, chat_name)
            else:
                text = tl(update.effective_message, "This user has {}/{} warning, for the following reasons:").format(num_warns, limit)
            for reason in reasons:
                text += "\n - {}".format(reason)

            msgs = split_message(text)
            for msg in msgs:
                send_message(update.effective_message, msg, parse_mode="markdown")
        else:
            if conn:
                send_message(update.effective_message, 
                    tl(update.effective_message, "This user has {}/{} warning on *{}*, but there's no reason for it.").format(num_warns, limit, chat_name), parse_mode="markdown")
            else:
                send_message(update.effective_message, 
                    tl(update.effective_message, "This user has {}/{} warning, but there's no reason for it.").format(num_warns, limit))
    else:
        if conn:
            send_message(update.effective_message, tl(update.effective_message, "This user has not received any warnings on *{}*!").format(chat_name), parse_mode="markdown")
        else:
            send_message(update.effective_message, tl(update.effective_message, "This user hasn't received any warnings yet!"))


# Dispatcher handler stop - do not async
#@spamcheck
@user_admin
@user_can_ban
def add_warn_filter(update, context):
    chat = update.effective_chat  # type: Optional[Chat]
    msg = update.effective_message  # type: Optional[Message]
    user = update.effective_user  # type: Optional[User]

    conn = connected(context.bot, update, chat, user.id, need_admin=True)
    if conn:
        chat = dispatcher.bot.getChat(conn)
        chat_id = conn
        chat_name = dispatcher.bot.getChat(conn).title
    else:
        if update.effective_message.chat.type == "private":
            send_message(update.effective_message, tl(update.effective_message, "You can do this command on groups, not on PM"))
            return ""
        chat = update.effective_chat
        chat_id = update.effective_chat.id
        chat_name = update.effective_message.chat.title

    args = msg.text.split(None, 1)  # use python's maxsplit to separate Cmd, keyword, and reply_text

    if len(args) < 2:
        return

    extracted = split_quotes(args[1])

    if len(extracted) >= 2:
        # set trigger -> lower, so as to avoid adding duplicate filters with different cases
        keyword = extracted[0].lower()
        content = extracted[1]

    else:
        return

    # Note: perhaps handlers can be removed somehow using sql.get_chat_filters
    for handler in dispatcher.handlers.get(WARN_HANDLER_GROUP, []):
        if handler.filters == (keyword, chat.id):
            dispatcher.remove_handler(handler, WARN_HANDLER_GROUP)

    sql.add_warn_filter(chat.id, keyword, content)

    if conn:
        text = tl(update.effective_message, "Warn handler added for '{}' on *{}*!").format(keyword, chat_name)
    else:
        text = tl(update.effective_message, "Warn handlers added for '{}'!").format(keyword)
    send_message(update.effective_message, text, parse_mode="markdown")
    raise DispatcherHandlerStop


#@spamcheck
@user_admin
@user_can_ban
def remove_warn_filter(update, context):
    chat = update.effective_chat  # type: Optional[Chat]
    msg = update.effective_message  # type: Optional[Message]
    user = update.effective_user  # type: Optional[User]

    conn = connected(context.bot, update, chat, user.id, need_admin=True)
    if conn:
        chat = dispatcher.bot.getChat(conn)
        chat_id = conn
        chat_name = dispatcher.bot.getChat(conn).title
    else:
        if update.effective_message.chat.type == "private":
            send_message(update.effective_message, tl(update.effective_message, "You can do this command in the group, not the PM"))
            return ""
        chat = update.effective_chat
        chat_id = update.effective_chat.id
        chat_name = update.effective_message.chat.title

    args = msg.text.split(None, 1)  # use python's maxsplit to separate Cmd, keyword, and reply_text

    if len(args) < 2:
        return

    extracted = split_quotes(args[1])

    if len(extracted) < 1:
        return

    chat_filters = sql.get_chat_warn_triggers(chat.id)
    if not chat_filters:
        if conn:
            text = tl(update.effective_message, "No warning filter on *{}*!").format(chat_name)
        else:
            text = tl(update.effective_message, "No warning filters are active here!")
        send_message(update.effective_message, text)
        return

    nowarn = 0
    inwarn = 0
    success = ""
    fail = ""
    teks = args[1].split(" ")
    for x in range(len(teks)):
        to_remove = teks[x]
        if to_remove not in chat_filters:
            fail += "`{}` ".format(to_remove)
            nowarn += 1
        for filt in chat_filters:
            if filt == to_remove:
                sql.remove_warn_filter(chat.id, to_remove)
                success += "`{}` ".format(to_remove)
                inwarn += 1
    if nowarn == 0:
        if conn:
            text = tl(update.effective_message, "Yes, I will stop warning people to {} *{}*.").format(success, chat_name)
        else:
            text = tl(update.effective_message, "Yes, I will stop warning people to {}.").format(success)
        send_message(update.effective_message, text, parse_mode=ParseMode.MARKDOWN)
        raise DispatcherHandlerStop
    elif inwarn == 0:
        if conn:
            text = tl(update.effective_message, "Failed to delete color filter for {} on *{}*.").format(fail, chat_name)
        else:
            text = tl(update.effective_message, "Failed to delete color filter for {}.").format(fail)
        send_message(update.effective_message, text, parse_mode=ParseMode.MARKDOWN)
        raise DispatcherHandlerStop
    else:
        if conn:
            text = tl(update.effective_message, "Yes, I will stop warning people to {}.\nAnd failed to remove the color filter for {}.\rReturn *{}*").format(success, fail, chat_name)
        else:
            text = tl(update.effective_message, "Yes, I will stop warning people to {}.\nDanya failed to remove the color filter for {}.").format(success, fail)
        send_message(update.effective_message, text, parse_mode=ParseMode.MARKDOWN)
        raise DispatcherHandlerStop

    """
    if not chat_filters:
        send_message(update.effective_message, "Tidak ada filter peringatan aktif di sini!")
        return

    for filt in chat_filters:
        if filt == to_remove:
            sql.remove_warn_filter(chat.id, to_remove)
                send_message(update.effective_message, "Ya, saya akan berhenti memperingatkan orang-orang untuk {}.".format(to_remove))
                raise DispatcherHandlerStop
    """

    if conn:
        text = tl(update.effective_message, "That's not a warning filter at the moment - run /warnlist for all active warning filters on *{}*.")
    else:
        text = tl(update.effective_message, "It is not a warning filter at this time - run /warnlist for all active warning filtersq.")
    send_message(update.effective_message, text, parse_mode="markdown")


#@spamcheck
@run_async
def list_warn_filters(update, context):
    chat = update.effective_chat  # type: Optional[Chat]
    user = update.effective_user  # type: Optional[User]

    conn = connected(context.bot, update, chat, user.id, need_admin=False)
    if conn:
        chat = dispatcher.bot.getChat(conn)
        chat_id = conn
        chat_name = dispatcher.bot.getChat(conn).title
    else:
        if update.effective_message.chat.type == "private":
            send_message(update.effective_message, tl(update.effective_message, "You can do this command in the group, not the PM"))
            return ""
        chat = update.effective_chat
        chat_id = update.effective_chat.id
        chat_name = update.effective_message.chat.title

    all_handlers = sql.get_chat_warn_triggers(chat.id)

    if not all_handlers:
        if conn:
            text = tl(update.effective_message, "No warning filter on *{}*!").format(chat_name)
        else:
            text = tl(update.effective_message, "No warning filters are active here!")
        send_message(update.effective_message, text, parse_mode="markdown")
        return

    filter_list = tl(update.effective_message, "CURRENT_WARNING_FILTER_STRING")
    if conn:
        filter_list = filter_list.replace(tl(update.effective_message, 'this chat'), tl(update.effective_message, 'chat *{}*').format(chat_name))
    for keyword in all_handlers:
        entry = " - {}\n".format(html.escape(keyword))
        if len(entry) + len(filter_list) > telegram.MAX_MESSAGE_LENGTH:
            send_message(update.effective_message, filter_list, parse_mode=ParseMode.HTML)
            filter_list = entry
        else:
            filter_list += entry

    if not filter_list == tl(update.effective_message, "CURRENT_WARNING_FILTER_STRING"):
        send_message(update.effective_message, filter_list, parse_mode=ParseMode.HTML)


@run_async
@loggable
def reply_filter(update, context) -> str:
    chat = update.effective_chat  # type: Optional[Chat]
    user = update.effective_user  # type: Optional[Message]
    message = update.effective_message  # type: Optional[Message]
    
    chat_id = str(chat.id)[1:] 
    approve_list = list(REDIS.sunion(f'approve_list_{chat_id}'))
    target_user = mention_html(user.id, user.first_name)
    if target_user in approve_list:
        return
    chat_warn_filters = sql.get_chat_warn_triggers(chat.id)
    to_match = extract_text(message)
    if not to_match:
        return ""

    for keyword in chat_warn_filters:
        pattern = r"( |^|[^\w])" + re.escape(keyword) + r"( |$|[^\w])"
        if re.search(pattern, to_match, flags=re.IGNORECASE):
            user = update.effective_user  # type: Optional[User]
            warn_filter = sql.get_warn_filter(chat.id, keyword)
            bot = context.bot
            return warn(bot, user, chat, warn_filter.reply, message)
    return ""


@run_async
#@spamcheck
@user_admin
@user_can_ban
@loggable
def set_warn_limit(update, context) -> str:
    chat = update.effective_chat  # type: Optional[Chat]
    user = update.effective_user  # type: Optional[User]
    msg = update.effective_message  # type: Optional[Message]
    args = context.args

    conn = connected(context.bot, update, chat, user.id, need_admin=True)
    if conn:
        chat = dispatcher.bot.getChat(conn)
        chat_id = conn
        chat_name = dispatcher.bot.getChat(conn).title
    else:
        if update.effective_message.chat.type == "private":
            send_message(update.effective_message, tl(update.effective_message, "You can do this command in the group, not the PM"))
            return ""
        chat = update.effective_chat
        chat_id = update.effective_chat.id
        chat_name = update.effective_message.chat.title

    if args:
        if args[0].isdigit():
            if int(args[0]) < 3:
                send_message(update.effective_message, tl(update.effective_message, "The minimum warning limit is 3!"))
            else:
                sql.set_warn_limit(chat.id, int(args[0]))
                if conn:
                    text = tl(update.effective_message, "Updated limit to be warned {} on *{}*").format(args[0], chat_name)
                else:
                    text = tl(update.effective_message, "Updated limits to be warned {}").format(args[0])
                send_message(update.effective_message, text, parse_mode="markdown")
                return "<b>{}:</b>" \
                       "\n#SET_WARN_LIMIT" \
                       "\n<b>Admin:</b> {}" \
                       "\nSet the warn limit to <code>{}</code>".format(html.escape(chat.title),
                                                                        mention_html(user.id, user.first_name), args[0])
        else:
            send_message(update.effective_message, tl(update.effective_message, "Give me the number!"))
    else:
        limit, soft_warn, warn_mode = sql.get_warn_setting(chat.id)
        if conn:
            text = tl(update.effective_message, "The current warning limit is {} on *{}*").format(limit, chat_name)
        else:
            text = tl(update.effective_message, "The current warning limit is {}").format(limit)
        send_message(update.effective_message, text, parse_mode="markdown")
    return ""


@run_async
#@spamcheck
@user_admin
def set_warn_strength(update, context):
    chat = update.effective_chat  # type: Optional[Chat]
    user = update.effective_user  # type: Optional[User]
    msg = update.effective_message  # type: Optional[Message]
    args = context.args

    conn = connected(context.bot, update, chat, user.id, need_admin=True)
    if conn:
        chat = dispatcher.bot.getChat(conn)
        chat_id = conn
        chat_name = dispatcher.bot.getChat(conn).title
    else:
        if update.effective_message.chat.type == "private":
            send_message(update.effective_message, tl(update.effective_message, "You can do this command in the group, not the PM"))
            return ""
        chat = update.effective_chat
        chat_id = update.effective_chat.id
        chat_name = update.effective_message.chat.title

    if args:
        if args[0].lower() in ("on", "yes"):
            sql.set_warn_strength(chat.id, False)
            if conn:
                text = "Too many warnings now will result in a block on *{}*!".format(chat_name)
            else:
                text = "Too many warnings now will result in a block!"
            send_message(update.effective_message, text, parse_mode="markdown")
            return "<b>{}:</b>\n" \
                   "<b>Admin:</b> {}\n" \
                   "Telah mengaktifkan strong warning. Users will be blocked.".format(html.escape(chat.title),
                                                                            mention_html(user.id, user.first_name))

        elif args[0].lower() in ("off", "no"):
            sql.set_warn_strength(chat.id, True)
            if conn:
                text = "Too many warnings will result in a kick on *{}*! Users will be able to join again.".format(chat_name)
            else:
                text = "Too many warnings will result in a kick! Users will be able to join again."
            send_message(update.effective_message, text, parse_mode="markdown")
            return "<b>{}:</b>\n" \
                   "<b>Admin:</b> {}\n" \
                   "Has disabled strong warning. Users will only be kicked.".format(html.escape(chat.title),
                                                                                  mention_html(user.id,
                                                                                               user.first_name))

        else:
            send_message(update.effective_message, "I only understood on/yes/no/off!")
    else:
        limit, soft_warn, warn_mode = sql.get_warn_setting(chat.id)
        if soft_warn:
            if conn:
                text = "The current warning is set to *kick* user when exceeding the limit at *{}*.".format(chat_name)
            else:
                text = "The current warning is set to *kick* when the user exceeds the limit."
            send_message(update.effective_message, text,
                           parse_mode=ParseMode.MARKDOWN)
        else:
            if conn:
                text = "The warning is currently set for *is blocked* user when exceeding the limit at *{}*.".format(chat_name)
            else:
                text = "The warning is currently set for *is blocked* user when exceeding limits."
            send_message(update.effective_message, text,
                           parse_mode=ParseMode.MARKDOWN)
    return ""


@run_async
#@spamcheck
@user_admin
def set_warn_mode(update, context):
    chat = update.effective_chat  # type: Optional[Chat]
    user = update.effective_user  # type: Optional[User]
    msg = update.effective_message  # type: Optional[Message]
    args = context.args

    conn = connected(context.bot, update, chat, user.id, need_admin=True)
    if conn:
        chat = dispatcher.bot.getChat(conn)
        chat_id = conn
        chat_name = dispatcher.bot.getChat(conn).title
    else:
        if update.effective_message.chat.type == "private":
            send_message(update.effective_message, tl(update.effective_message, "You can do this command in the group, not the PM"))
            return ""
        chat = update.effective_chat
        chat_id = update.effective_chat.id
        chat_name = update.effective_message.chat.title

    if args:
        if args[0].lower() in ("kick", "soft"):
            sql.set_warn_mode(chat.id, 1)
            if conn:
                text = tl(update.effective_message, "Too many warnings will now result kick on *{}*! Users will be able to join again.").format(chat_name)
            else:
                text = tl(update.effective_message, "Too many warnings will now result in a kick! Users will be able to join again.")
            send_message(update.effective_message, text, parse_mode="markdown")
            return "<b>{}:</b>\n" \
                   "<b>Admin:</b> {}\n" \
                   "Has changed the final warning to kick.".format(html.escape(chat.title),
                                                                            mention_html(user.id, user.first_name))

        elif args[0].lower() in ("ban", "banned", "hard"):
            sql.set_warn_mode(chat.id, 2)
            if conn:
                text = tl(update.effective_message, "Too many warnings will result in a block on *{}*!").format(chat_name)
            else:
                text = tl(update.effective_message, "Too many warnings will result in a block!")
            send_message(update.effective_message, text, parse_mode="markdown")
            return "<b>{}:</b>\n" \
                   "<b>Admin:</b> {}\n" \
                   "Has changed the final warning to banned.".format(html.escape(chat.title),
                                                                                  mention_html(user.id,
                                                                                               user.first_name))

        elif args[0].lower() in ("mute"):
            sql.set_warn_mode(chat.id, 3)
            if conn:
                text = tl(update.effective_message, "Too many warnings will result in mute on *{}*!").format(chat_name)
            else:
                text = tl(update.effective_message, "Too many warnings will result in mute!")
            send_message(update.effective_message, text, parse_mode="markdown")
            return "<b>{}:</b>\n" \
                   "<b>Admin:</b> {}\n" \
                   "Has changed the final warning to mute.".format(html.escape(chat.title),
                                                                                  mention_html(user.id,
                                                                                               user.first_name))

        else:
            send_message(update.effective_message, tl(update.effective_message, "I only understand kick /ban /mute!"))
    else:
        limit, soft_warn, warn_mode = sql.get_warn_setting(chat.id)
        if not soft_warn:
            if not warn_mode:
                if conn:
                    text = tl(update.effective_message, "The current warning is set to *kick* user when exceeding the limit at *{}*.").format(chat_name)
                else:
                    text = tl(update.effective_message, "The current warning is set to *kick* user when exceeding limits.")
            elif warn_mode == 1:
                if conn:
                    text = tl(update.effective_message, "The warning is currently set to *kick* user when exceeding the limit in q *{}*.").format(chat_name)
                else:
                    text = tl(update.effective_message, "The current warning is set to *kick* when the user exceeds the limit.")
            elif warn_mode == 2:
                if conn:
                    text = tl(update.effective_message, "The current warning is set to *block* user when exceeding the limit at *{}*.").format(chat_name)
                else:
                    text = tl(update.effective_message, "The warning is currently set to *block* the user when it exceeds the limit.")
            elif warn_mode == 3:
                if conn:
                    text = tl(update.effective_message, "The current warning is set to *mute* the user when it exceeds the limit at *{}*.").format(chat_name)
                else:
                    text = tl(update.effective_message, "The current warning is set to *mute* the user when it exceeds the limit.")
            send_message(update.effective_message, text,
                           parse_mode=ParseMode.MARKDOWN)
        else:
            if conn:
                text = tl(update.effective_message, "The warning is currently set to *block* users when they exceed the limit on *{}*.").format(chat_name)
            else:
                text = tl(update.effective_message, "Warning is currently set to *block* users when exceeding the limit.")
            send_message(update.effective_message, text,
                           parse_mode=ParseMode.MARKDOWN)
    return ""


def __stats__():
    return tl(OWNER_ID, "{} all over warning, on {} chat.\n" \
           "{} filter warn, on {}.").format(sql.num_warns(), sql.num_warn_chats(),
                                                      sql.num_warn_filters(), sql.num_warn_filter_chats())


def __import_data__(chat_id, data):
    for user_id, count in data.get('warns', {}).items():
        for x in range(int(count)):
            sql.warn_user(user_id, chat_id)


def __migrate__(old_chat_id, new_chat_id):
    sql.migrate_chat(old_chat_id, new_chat_id)


def __chat_settings__(chat_id, user_id):
    num_warn_filters = sql.num_warn_chat_filters(chat_id)
    limit, soft_warn, warn_mode = sql.get_warn_setting(chat_id)
    return tl(user_id, "This chat has a `{}` warning filter. Warning {}} is required " \
           "before the user will get it *{}*.").format(num_warn_filters, limit, "kick" if soft_warn else "blocking")

"""
def __chat_settings_btn__(chat_id, user_id):
    limit, soft_warn, warn_mode = sql.get_warn_setting(chat_id)
    button = []
    button.append([InlineKeyboardButton(text="➖", callback_data="set_wlim=-|{}".format(chat_id)),
            InlineKeyboardButton(text="Limit {}".format(limit), callback_data="set_wlim=?|{}".format(chat_id)),
            InlineKeyboardButton(text="➕", callback_data="set_wlim=+|{}".format(chat_id))])
    button.append([InlineKeyboardButton(text="{}".format("Kick" if soft_warn else "Block"), callback_data="set_wlim=exec|{}".format(chat_id))])
    return button

def WARN_EDITBTN(update, context):
    query = update.callback_query
    user = update.effective_user
    print("User {} clicked button WARN EDIT".format(user.id))
    qdata = query.data.split("=")[1].split("|")[0]
    chat_id = query.data.split("|")[1]
    if qdata == "?":
        context.bot.answerCallbackQuery(query.id, "Batas dari peringatan. Jika peringatan melewati batas maka akan di eksekusi.", show_alert=True)
    if qdata == "-":
        button = []
        limit, soft_warn, warn_mode = sql.get_warn_setting(chat_id)
        limit = int(limit)-1
        if limit <= 2:
            context.bot.answerCallbackQuery(query.id, "Batas limit Tidak boleh kurang dari 3", show_alert=True)
            return
        sql.set_warn_limit(chat_id, int(limit))
        chat = context.bot.get_chat(chat_id)
        text = "*{}* has the following settings for the module * Warning*:\n\n".format(escape_markdown(chat.title))
        text += "The maximum warning limit has been set to `{}`. Needed `{}` warning " \
           "before the user will get it *{}*.".format(limit, limit, "kick" if soft_warn else "blocking")
        button.append([InlineKeyboardButton(text="➖", callback_data="set_wlim=-|{}".format(chat_id)),
                InlineKeyboardButton(text="Limit {}".format(limit), callback_data="set_wlim=?|{}".format(chat_id)),
                InlineKeyboardButton(text="➕", callback_data="set_wlim=+|{}".format(chat_id))])
        button.append([InlineKeyboardButton(text="{}".format(" Kick" if soft_warn else " Block"), callback_data="set_wlim=exec|{}".format(chat_id))])
        button.append([InlineKeyboardButton(text="Kembali", callback_data="stngs_back({})".format(chat_id))])
        query.message.edit_text(text=text,
                                  parse_mode=ParseMode.MARKDOWN,
                                  reply_markup=InlineKeyboardMarkup(button))
        context.bot.answer_callback_query(query.id)
    if qdata == "+":
        button = []
        limit, soft_warn, warn_mode = sql.get_warn_setting(chat_id)
        limit = int(limit)+1
        if limit <= 0:
            context.bot.answerCallbackQuery(query.id, "Batas limit Tidak boleh kurang dari 0", show_alert=True)
            return
        sql.set_warn_limit(chat_id, int(limit))
        chat = context.bot.get_chat(chat_id)
        text = "*{}* has the following settings for the module *Warning*:\n\n".format(escape_markdown(chat.title))
        text += "The maximum warning limit has been set to `{}`. Needed `{}` warning " \
           "before the user will get it *{}*.".format(limit, limit, "kick" if soft_warn else "blocking")
        button.append([InlineKeyboardButton(text="➖", callback_data="set_wlim=-|{}".format(chat_id)),
                InlineKeyboardButton(text="Limit {}".format(limit), callback_data="set_wlim=?|{}".format(chat_id)),
                InlineKeyboardButton(text="➕", callback_data="set_wlim=+|{}".format(chat_id))])
        button.append([InlineKeyboardButton(text="{}".format("Kick" if soft_warn else "Block"), callback_data="set_wlim=exec|{}".format(chat_id))])
        button.append([InlineKeyboardButton(text="Kembali", callback_data="stngs_back({})".format(chat_id))])
        query.message.edit_text(text=text,
                                  parse_mode=ParseMode.MARKDOWN,
                                  reply_markup=InlineKeyboardMarkup(button))
        context.bot.answer_callback_query(query.id)
    if qdata == "exec":
        button = []
        limit, soft_warn, warn_mode = sql.get_warn_setting(chat_id)
        if soft_warn:
            exc = "Blokir"
            sql.set_warn_strength(chat_id, False)
            soft_warn = False
        else:
            exc = "Tendang"
            sql.set_warn_strength(chat_id, True)
            soft_warn = True
        chat = context.bot.get_chat(chat_id)
        text = "*{}* has the following settings for the module * Warning*:\n\n".format(escape_markdown(chat.title))
        text += "The user will be logged in `{}` if it is outside the warning limit. Needed `{}` warning " \
           "before the user will get it *{}*.".format(exc, limit, "kick" if soft_warn else "blocking")
        button.append([InlineKeyboardButton(text="➖", callback_data="set_wlim=-|{}".format(chat_id)),
                InlineKeyboardButton(text="Limit {}".format(limit), callback_data="set_wlim=?|{}".format(chat_id)),
                InlineKeyboardButton(text="➕", callback_data="set_wlim=+|{}".format(chat_id))])
        button.append([InlineKeyboardButton(text="{}".format("Kick" if soft_warn else "Block"), callback_data="set_wlim=exec|{}".format(chat_id))])
        button.append([InlineKeyboardButton(text="Back", callback_data="stngs_back({})".format(chat_id))])
        query.message.edit_text(text=text,
                                  parse_mode=ParseMode.MARKDOWN,
                                  reply_markup=InlineKeyboardMarkup(button))
        context.bot.answer_callback_query(query.id)
"""


__help__ = """
 • `/warns <userhandle>`*:* get a user's number, and reason, of warns.
 • `/warnlist`*:* list of all current warning filters
*Admins only:*
 • `/warn <userhandle>`*:* warn a user. After 3 warns, the user will be banned from the group. Can also be used as a reply.
 • `/dwarn same as warn but this one delete targeted message and warn user`
 • `/resetwarn <userhandle>`*:* reset the warns for a user. Can also be used as a reply.
 • `/addwarn <keyword> <reply message>`*:* set a warning filter on a certain keyword. If you want your keyword to \
be a sentence, encompass it with quotes, as such: `/addwarn "very angry" This is an angry user`. 
 • `/nowarn <keyword>`*:* stop a warning filter
 • `/warnlimit <num>`*:* set the warning limit
 • `/setwarnmode`: `kick`/ `ban` / `mute` : set chat warn mode
 • `/strongwarn <on/yes/off/no>`*:* If set to on, exceeding the warn limit will result in a ban. Else, will just punch.
"""

__mod_name__ = "Warnings"

WARN_HANDLER = CommandHandler(["warn","dwarn"], warn_user, pass_args=True)#, filters=Filters.group)
#DWARN_HANDLER = CommandHandler("dwarn", dwarn_user, pass_args=True)#, filters=Filters.group)
RESET_WARN_HANDLER = CommandHandler(["resetwarn", "resetwarns", "rmwarn"], reset_warns, pass_args=True)#, filters=Filters.group)
CALLBACK_QUERY_HANDLER = CallbackQueryHandler(button, pattern=r"rm_warn")
MYWARNS_HANDLER = DisableAbleCommandHandler("warns", warns, pass_args=True)#, filters=Filters.group)
ADD_WARN_HANDLER = CommandHandler("addwarn", add_warn_filter)#, filters=Filters.group)
RM_WARN_HANDLER = CommandHandler(["nowarn", "stopwarn"], remove_warn_filter)#, filters=Filters.group)
LIST_WARN_HANDLER = DisableAbleCommandHandler(["warnlist", "warnfilters"], list_warn_filters)#, filters=Filters.group, admin_ok=True)
WARN_FILTER_HANDLER = MessageHandler(CustomFilters.has_text & Filters.group, reply_filter)
WARN_LIMIT_HANDLER = CommandHandler("warnlimit", set_warn_limit, pass_args=True)#, filters=Filters.group)
WARN_STRENGTH_HANDLER = CommandHandler("strongwarn", set_warn_strength, pass_args=True)#, filters=Filters.group)
WARN_MODE_HANDLER = CommandHandler("setwarnmode", set_warn_mode, pass_args=True)
# WARN_BTNSET_HANDLER = CallbackQueryHandler(WARN_EDITBTN, pattern=r"set_wlim")

dispatcher.add_handler(WARN_HANDLER)
#dispatcher.add_handler(DWARN_HANDLER)
dispatcher.add_handler(CALLBACK_QUERY_HANDLER)
dispatcher.add_handler(RESET_WARN_HANDLER)
dispatcher.add_handler(MYWARNS_HANDLER)
dispatcher.add_handler(ADD_WARN_HANDLER)
dispatcher.add_handler(RM_WARN_HANDLER)
dispatcher.add_handler(LIST_WARN_HANDLER)
dispatcher.add_handler(WARN_LIMIT_HANDLER)
dispatcher.add_handler(WARN_MODE_HANDLER)
dispatcher.add_handler(WARN_FILTER_HANDLER, WARN_HANDLER_GROUP)
# dispatcher.add_handler(WARN_BTNSET_HANDLER)