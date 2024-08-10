import logging
import re
import os
import sys
import asyncio

sys.path.append(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from app.scripts.GroupSwitch.main import *
from app.scripts.GroupManager.welcome_farewell import *
from app.scripts.GroupManager.group_management import *


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
def load_invite_chain_switch(group_id):
    return load_switch(group_id, "invite_chain_switch")


# 保存邀请链开关
def save_invite_chain_switch(group_id, switch):
    save_switch(group_id, "invite_chain_switch", switch)


# 加载邀请链
def load_invite_chain(group_id):
    try:
        with open(
            os.path.join(DATA_DIR, f"{group_id}.json"),
            "r",
            encoding="utf-8",
        ) as f:
            return json.load(f)
    except FileNotFoundError:
        return []


async def view_invite_chain(websocket, group_id, target_user_id):
    if not load_invite_chain_switch(group_id):
        await send_group_msg(websocket, group_id, "邀请链功能已关闭。")
        return

    invite_chain = load_invite_chain(group_id)
    if not invite_chain:
        await send_group_msg(websocket, group_id, "没有找到邀请链。")
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
        invite_chain_message = "邀请链:\n\n"
        for inviter in chain:
            invite_chain_message += f"【{inviter['operator_id']}】邀请了【{inviter['user_id']}】（{inviter['type']}）\n邀请时间：{inviter['date']}\n\n"
    else:
        invite_chain_message = "没有找到相关的邀请链。"

    await send_group_msg(websocket, group_id, invite_chain_message)


async def save_invite_chain(group_id, user_id, operator_id):
    if not load_invite_chain_switch(group_id):
        return

    invite_chain = load_invite_chain(group_id)
    invite_chain.append(
        {
            "user_id": str(user_id),
            "operator_id": str(operator_id),
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    )

    with open(
        os.path.join(DATA_DIR, f"invite_chain_{group_id}.json"), "w", encoding="utf-8"
    ) as f:
        json.dump(invite_chain, f, ensure_ascii=False, indent=4)


async def handle_InviteChain_group_notice(websocket, msg):
    try:
        # 使用get函数安全的获取参数，以防不存在导致跳出异常
        operator_id = msg.get("operator_id", "")
        sub_type = msg.get("sub_type", "")
        user_id = msg.get("user_id", "")
        group_id = msg.get("group_id", "")

        if msg["notice_type"] == "group_increase":
            await handle_welcome_message(websocket, group_id, user_id)
            if (
                sub_type == "invite" or sub_type == "approve"
            ) and load_invite_chain_switch(group_id):
                await save_invite_chain(group_id, user_id, operator_id)
                await send_group_msg(
                    websocket,
                    group_id,
                    f"已记录 [CQ:at,qq={user_id}] 的邀请链，操作者为 [CQ:at,qq={operator_id}] ，请勿在群内发送违规信息",
                )

    except Exception as e:
        logging.error(f"处理邀请链时发生错误: {e}")


async def handle_InviteChain_group_message(websocket, msg):

    user_id = msg["user_id"]
    group_id = msg["group_id"]
    raw_message = msg["raw_message"]
    role = msg["sender"]["role"]
    message_id = int(msg["message_id"])



    # 查看邀请链
    if raw_message.startswith("view_invite_chain ") or raw_message.startswith(
        "查看邀请链 "
    ):
        target_user_id = raw_message.split(" ", 1)[1].strip()
        await view_invite_chain(websocket, group_id, target_user_id)
