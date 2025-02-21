import logging
import re
import os
import sys
import asyncio

sys.path.append(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from app.switch import load_switch, save_switch
from app.scripts.GroupManager.group_management import *
from app.scripts.BlacklistSystem.main import is_blacklisted

from app.api import *
from app.config import owner_id


DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "InviteChain",
)


# 是否是群主
def is_group_owner(role):
    return role == "owner"


# 是否是管理员
def is_group_admin(role):
    return role == "admin"


# 是否是管理员或群主或root管理员
def is_authorized(role, user_id):
    is_admin = is_group_admin(role)
    is_owner = is_group_owner(role)
    return (is_admin or is_owner) or (user_id in owner_id)


# 加载邀请链开关
def load_InviteChain_switch(group_id):
    return load_switch(group_id, "邀请链记录")


# 保存邀请链开关
def save_InviteChain_switch(group_id, switch):
    save_switch(group_id, "邀请链记录", switch)


# 加载邀请链
def load_InviteChain(group_id):
    try:
        with open(
            os.path.join(DATA_DIR, f"{group_id}.json"),
            "r",
            encoding="utf-8",
        ) as f:
            return json.load(f)
    except FileNotFoundError:
        return []


# 查看某人邀请的用户
def get_invited_users(group_id, target_user_id):
    if not load_InviteChain_switch(group_id):
        return None

    invite_chain = load_InviteChain(group_id)

    if not invite_chain:
        return None

    invited_users = [
        inviter["user_id"]
        for inviter in invite_chain
        if inviter["operator_id"] == target_user_id
    ]

    # 去重
    invited_users = set(invited_users)

    if invited_users:
        return ",".join(invited_users)
    else:
        return None


# 查看邀请链
async def view_InviteChain(websocket, group_id, target_user_id, message_id):
    if not load_InviteChain_switch(group_id):
        await send_group_msg(
            websocket, group_id, f"[CQ:reply,id={message_id}]邀请链功能已关闭。"
        )
        return

    invite_chain = load_InviteChain(group_id)
    if not invite_chain:
        await send_group_msg(
            websocket, group_id, f"[CQ:reply,id={message_id}]没有找到邀请链。"
        )
        return

    def find_invite_chain(target_user_id, chain, visited):
        for inviter in invite_chain:
            if (
                inviter["operator_id"] == target_user_id
                and inviter["user_id"] not in visited
            ):
                chain.append({"type": "主动邀请", **inviter})
                visited.add(inviter["user_id"])
                find_invite_chain(inviter["user_id"], chain, visited)
            elif (
                inviter["user_id"] == target_user_id
                and inviter["user_id"] not in visited
            ):
                chain.append({"type": "被动邀请", **inviter})
                visited.add(inviter["user_id"])
                find_invite_chain(inviter["operator_id"], chain, visited)

    chain = []
    visited = set()
    find_invite_chain(target_user_id, chain, visited)

    if chain:
        blacklisted_users = [
            inviter["user_id"]
            for inviter in chain
            if is_blacklisted(group_id, inviter["user_id"])
        ]
        if blacklisted_users:
            await send_group_msg(
                websocket,
                group_id,
                f"[CQ:reply,id={message_id}]在邀请链中发现了黑名单用户: {', '.join(blacklisted_users)}，请注意甄别所有相关用户的身份",
            )

        if len(chain) > 10:  # 设置超过10条消息时使用合并消息发送
            await send_group_msg(
                websocket,
                group_id,
                f"[CQ:reply,id={message_id}]邀请链消息过长，将合并发送，共{len(chain)}条，请耐心等待。",
            )
            # 每五条信息创建一个节点
            messages = []
            message_content = ""
            for index, inviter in enumerate(chain):
                message_content += f"[{inviter['operator_id']}]邀请了[{inviter['user_id']}]\n邀请类型：{inviter['type']}\n邀请时间：{inviter['date']}\n\n"
                if (index + 1) % 5 == 0 or index == len(
                    chain
                ) - 1:  # 每五条或者最后一条
                    messages.append(
                        {
                            "type": "node",
                            "data": {
                                "name": "邀请链消息",
                                "uin": "2769731875",
                                "content": message_content,
                            },
                        }
                    )
                    message_content = ""  # 重置消息内容，为下一个节点准备
            await send_forward_msg(websocket, group_id, messages)
        else:
            invite_chain_message = f"[CQ:reply,id={message_id}]"
            invite_chain_message += "邀请链:\n\n"
            for inviter in chain:
                invite_chain_message += f"[{inviter['operator_id']}]邀请了[{inviter['user_id']}]\n邀请类型：{inviter['type']}\n邀请时间：{inviter['date']}\n\n"
            await send_group_msg(websocket, group_id, invite_chain_message)
    else:
        invite_chain_message = "没有找到相关的邀请链。"
        await send_group_msg(
            websocket, group_id, f"[CQ:reply,id={message_id}]{invite_chain_message}"
        )


# 保存邀请链
async def save_invite_chain(group_id, user_id, operator_id):

    invite_chain = load_InviteChain(group_id)
    invite_chain.append(
        {
            "user_id": str(user_id),
            "operator_id": str(operator_id),
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    )

    with open(os.path.join(DATA_DIR, f"{group_id}.json"), "w", encoding="utf-8") as f:
        json.dump(invite_chain, f, ensure_ascii=False, indent=4)


# 处理邀请链群通知
async def handle_InviteChain_group_notice(websocket, msg):
    try:
        # 确保数据目录存在
        os.makedirs(DATA_DIR, exist_ok=True)
        # 使用get函数安全的获取参数，以防不存在导致跳出异常
        operator_id = str(msg.get("operator_id", ""))
        sub_type = str(msg.get("sub_type", ""))
        user_id = str(msg.get("user_id", ""))
        group_id = str(msg.get("group_id", ""))
        notice_type = str(msg.get("notice_type", ""))

        # 限定范围，只处理入群事件
        if notice_type != "group_increase":
            return

        # 获取操作者的信息
        operator_info = await get_group_member_info(websocket, group_id, operator_id)
        operator_role = operator_info.get("data", {}).get("role", "")

        # 如果操作者是群主或管理或root，则不记录邀请链
        if is_authorized(operator_role, operator_id):
            logging.info(f"操作者 {operator_id} 有管理权限，不记录邀请链")
            return

        if load_InviteChain_switch(group_id):
            if msg["notice_type"] == "group_increase":
                if sub_type == "invite" or sub_type == "approve":
                    await save_invite_chain(group_id, user_id, operator_id)
                    await send_group_msg(
                        websocket,
                        group_id,
                        f"[+]已记录[CQ:at,qq={user_id}][{user_id}]的邀请链，操作者为[CQ:at,qq={operator_id}][{operator_id}]，请勿在群内发送违规信息",
                    )

                    if is_blacklisted(group_id, user_id):
                        logging.info(f"邀请链发现黑名单用户[{user_id}]，将踢出群聊。")
                        await set_group_kick(websocket, group_id, user_id)
                        await set_group_kick(websocket, group_id, operator_id)

                        logging.info(
                            f"[+]发现[{operator_id}]邀请了[{user_id}]，该用户为黑名单用户，将踢出邀请者[{operator_id}]和被邀请者[{user_id}]，并不再接受入群。"
                        )

                        await send_group_msg(
                            websocket,
                            group_id,
                            f"[+]发现[{operator_id}]邀请了[{user_id}]，该用户为黑名单用户，将踢出邀请者[{operator_id}]和被邀请者[{user_id}]，并不再接受入群。",
                        )

    except Exception as e:
        logging.error(f"处理邀请链时发生错误: {e}")


# 邀请链菜单
async def InviteChain(websocket, group_id, message_id):
    message = (
        f"[CQ:reply,id={message_id}]\n"
        + """
邀请链系统

icon 开启邀请链
icoff 关闭邀请链
iclist@查看邀请链
"""
    )
    await send_group_msg(websocket, group_id, message)


# 处理邀请链群组消息
async def handle_InviteChain_group_commands(
    websocket, group_id, message_id, raw_message, user_id, role
):
    if raw_message == "invitechain":
        await InviteChain(websocket, group_id, message_id)
        return

    if not is_authorized(role, user_id):
        return

    if raw_message.startswith("iclist"):
        if load_InviteChain_switch(group_id):
            match = re.search(r"(\d+)", raw_message)
            if match:
                target_user_id = match.group(1)
                logging.info(f"查看邀请链 {target_user_id}")
                await view_InviteChain(websocket, group_id, target_user_id, message_id)

    elif raw_message == "icon":
        logging.info(f"开启邀请链 {group_id}")
        if not load_InviteChain_switch(group_id):
            save_InviteChain_switch(group_id, True)
            await send_group_msg(
                websocket, group_id, f"[CQ:reply,id={message_id}]邀请链功能已开启。"
            )
        else:
            await send_group_msg(
                websocket,
                group_id,
                f"[CQ:reply,id={message_id}]邀请链功能已开启，无需再次开启。",
            )

    elif raw_message == "icoff":
        logging.info(f"关闭邀请链 {group_id}")
        if load_InviteChain_switch(group_id):
            save_InviteChain_switch(group_id, False)
            await send_group_msg(
                websocket, group_id, f"[CQ:reply,id={message_id}]邀请链功能已关闭。"
            )
        else:
            await send_group_msg(
                websocket,
                group_id,
                f"[CQ:reply,id={message_id}]邀请链功能已关闭，无需再次关闭。",
            )


# 统一事件处理入口
async def handle_events(websocket, msg):
    """统一事件处理入口"""
    post_type = msg.get("post_type", "response")
    try:
        if msg.get("status") == "ok":
            return

        post_type = msg.get("post_type")

        if post_type == "meta_event":
            return

        elif post_type == "message":
            message_type = msg.get("message_type")
            if message_type == "group":
                group_id = str(msg.get("group_id", ""))
                message_id = str(msg.get("message_id", ""))
                raw_message = str(msg.get("raw_message", ""))
                user_id = str(msg.get("user_id", ""))
                role = str(msg.get("sender", {}).get("role", ""))

                await handle_InviteChain_group_commands(
                    websocket, group_id, message_id, raw_message, user_id, role
                )

            elif message_type == "private":
                return

        elif post_type == "notice":
            await handle_InviteChain_group_notice(websocket, msg)

    except Exception as e:
        error_type = {
            "message": "消息",
            "notice": "通知",
            "request": "请求",
            "meta_event": "元事件",
        }.get(post_type, "未知")

        logging.error(f"处理InviteChain{error_type}事件失败: {e}")

        if post_type == "message":
            message_type = msg.get("message_type")
            if message_type == "group":
                await send_group_msg(
                    websocket,
                    msg.get("group_id"),
                    f"处理InviteChain{error_type}事件失败，错误信息：{str(e)}",
                )
            elif message_type == "private":
                await send_private_msg(
                    websocket,
                    msg.get("user_id"),
                    f"处理InviteChain{error_type}事件失败，错误信息：{str(e)}",
                )
