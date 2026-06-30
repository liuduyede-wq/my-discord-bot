import discord
from discord.ext import commands
from discord import app_commands
import asyncio
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
from flask import Flask
from threading import Thread

# .envファイルからトークンを読み込む
load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# ユーザーごとのタイマー情報を保存
active_timers = {}
# ユーザーごとの通知設定を保存
user_settings = {}

def get_user_settings(user_id):
    if user_id not in user_settings:
        # 初期値に alert_disconnect も追加
        user_settings[user_id] = {"alert_5": True, "alert_1": True, "alert_disconnect": True}
    # 既存ユーザーで新しい設定項目がない場合の安全対策
    if "alert_disconnect" not in user_settings[user_id]:
        user_settings[user_id]["alert_disconnect"] = True
    return user_settings[user_id]

def get_alert_text(settings):
    a5 = settings["alert_5"]
    a1 = settings["alert_1"]
    ad = settings["alert_disconnect"]
    
    alerts = []
    if a5: alerts.append("5分前")
    if a1: alerts.append("1分前")
    if ad: alerts.append("退出時")
    
    if alerts:
        return f"({', '.join(alerts)}に教えるね！)"
    else:
        return "(ぼく静かにしてる！)"

@bot.event
async def on_ready():
    print(f'{bot.user} としてログインしました！')
    try:
        synced = await bot.tree.sync()
        print(f"{len(synced)}個のスラッシュコマンドを同期しました！")
    except Exception as e:
        print(e)

@bot.event
async def on_voice_state_update(member, before, after):
    if before.channel is not None and after.channel is None:
        if member.id in active_timers:
            active_timers[member.id]["task"].cancel()

async def wait_and_disconnect(interaction: discord.Interaction, total_seconds: float, end_message: str):
    user_id = interaction.user.id
    guild = interaction.guild
    settings = get_user_settings(user_id)
    
    try:
        target_time = datetime.now() + timedelta(seconds=total_seconds)
        
        # 5分前通知
        if total_seconds >= 300:
            await asyncio.sleep(total_seconds - 300)
            member = guild.get_member(user_id)
            if settings["alert_5"] and member and member.voice:
                await interaction.channel.send(f"{member.display_name}さん！ あと5分でばいばいの時間だよ！")
        
        # 1分前通知
        now = datetime.now()
        remaining = (target_time - now).total_seconds()
        if remaining > 60:
            await asyncio.sleep(remaining - 60)
            member = guild.get_member(user_id)
            if settings["alert_1"] and member and member.voice:
                await interaction.channel.send(f"{member.display_name}さん！ あと1分でばいばいの時間だよ！")

        # 切断時間まで待機
        now = datetime.now()
        remaining = (target_time - now).total_seconds()
        if remaining > 0: 
            await asyncio.sleep(remaining)
            
        # 切断する直前に「今の状態」を取り直す
        # 切断する直前に「今の状態」を取り直す
        member = guild.get_member(user_id)
        if member and member.voice:
            # ⭕️先にメッセージを送る！
            if settings["alert_disconnect"]:
                await interaction.channel.send(f"{member.display_name} {end_message}")
            
            # ⭕️メッセージを送り終わってから、通話を切断する！
            await member.move_to(None)
            
    except asyncio.CancelledError:
        pass
    finally:
        if user_id in active_timers: 
            del active_timers[user_id]

@bot.tree.command(name="at_time", description="指定した時刻に自動で通話を切断します")
@app_commands.describe(time_input="「23:30」のように入力")
async def at_time(interaction: discord.Interaction, time_input: str):
    if not interaction.user.voice:
        await interaction.response.send_message("まだみんなと通話してないみたい。ボイスチャンネルでぼくを呼んでね！", ephemeral=True)
        return
    try:
        now = datetime.now()
        target = now.replace(hour=int(time_input.split(":")[0]), minute=int(time_input.split(":")[1]), second=0, microsecond=0)
        if target < now: target += timedelta(days=1)
        wait_seconds = (target - now).total_seconds()
    except:
        await interaction.response.send_message("うーん。僕にはわかんないや。「23:30」みたいに入力してほしい！", ephemeral=True)
        return
    
    cancel_msg = ""
    if interaction.user.id in active_timers:
        cancel_msg = f"{active_timers[interaction.user.id]['target_time'].strftime('%H:%M')}じゃなくて、\n"
        active_timers[interaction.user.id]["task"].cancel()
    
    await interaction.response.send_message(f"{cancel_msg}**{target.strftime('%H:%M')}**に通話からばいばいするね！{get_alert_text(get_user_settings(interaction.user.id))}")
    active_timers[interaction.user.id] = {"task": asyncio.create_task(wait_and_disconnect(interaction, wait_seconds, "ばいばい！またね！")), "target_time": target}

@bot.tree.command(name="in_time", description="指定した時間経過後に通話を切断します")
@app_commands.describe(minutes="何分後に切断するか（数字）")
async def in_time(interaction: discord.Interaction, minutes: int):
    if not interaction.user.voice:
        await interaction.response.send_message("まだみんなと通話してないみたい。ボイスチャンネルでぼくを呼んでね！", ephemeral=True)
        return
    if minutes <= 0:
        await interaction.response.send_message("過去にはいけないよ！1分以上でお願い！", ephemeral=True)
        return
    
    target = datetime.now() + timedelta(minutes=minutes)
    cancel_msg = ""
    if interaction.user.id in active_timers:
        cancel_msg = f"{active_timers[interaction.user.id]['target_time'].strftime('%H:%M')}じゃなくて、\n"
        active_timers[interaction.user.id]["task"].cancel()
    
    await interaction.response.send_message(f"{cancel_msg}**{target.strftime('%H:%M')}**に通話からばいばいするね！{get_alert_text(get_user_settings(interaction.user.id))}")
    active_timers[interaction.user.id] = {"task": asyncio.create_task(wait_and_disconnect(interaction, minutes * 60, "ばいばい！またね！")), "target_time": target}

@bot.tree.command(name="cancel", description="切断タイマーを止めます")
async def cancel(interaction: discord.Interaction):
    if interaction.user.id in active_timers:
        active_timers[interaction.user.id]["task"].cancel()
        await interaction.response.send_message("やっぱりみんなといることにしたよ！")
    else:
        await interaction.response.send_message("今、設定されているタイマーはないよ！", ephemeral=True)

@bot.tree.command(name="check", description="設定を確認します")
async def check(interaction: discord.Interaction):
    user_id = interaction.user.id
    settings = get_user_settings(user_id)
    
    # 各アラートのON/OFF状態をわかりやすくテキスト化
    status_5 = "⭕️ ON" if settings["alert_5"] else "❌ OFF"
    status_1 = "⭕️ ON" if settings["alert_1"] else "❌ OFF"
    status_dc = "⭕️ ON" if settings["alert_disconnect"] else "❌ OFF"
    
    settings_text = f"\n\n【現在のアラート設定】\n・5分前通知: {status_5}\n・1分前通知: {status_1}\n・退出時メッセージ: {status_dc}"

    if user_id in active_timers:
        await interaction.response.send_message(f"**{active_timers[user_id]['target_time'].strftime('%H:%M')}**にばいばいする予定だよ！{settings_text}", ephemeral=True)
    else:
        await interaction.response.send_message(f"みんなとずっと一緒にいる予定だよ！{settings_text}", ephemeral=True)

@bot.tree.command(name="alert_5", description="5分前通知のON/OFF")
@app_commands.choices(status=[app_commands.Choice(name="on", value="on"), app_commands.Choice(name="off", value="off")])
async def alert_5(interaction: discord.Interaction, status: app_commands.Choice[str]):
    get_user_settings(interaction.user.id)["alert_5"] = (status.value == "on")
    await interaction.response.send_message("5分前になったら教えるね！" if status.value == "on" else "ぼく静かにしてる！", ephemeral=True)

@bot.tree.command(name="alert_1", description="1分前通知のON/OFF")
@app_commands.choices(status=[app_commands.Choice(name="on", value="on"), app_commands.Choice(name="off", value="off")])
async def alert_1(interaction: discord.Interaction, status: app_commands.Choice[str]):
    get_user_settings(interaction.user.id)["alert_1"] = (status.value == "on")
    await interaction.response.send_message("1分前になったら教えるね！" if status.value == "on" else "ぼく静かにしてる！", ephemeral=True)

@bot.tree.command(name="alert_disconnect", description="退出時メッセージのON/OFF")
@app_commands.choices(status=[app_commands.Choice(name="on", value="on"), app_commands.Choice(name="off", value="off")])
async def alert_disconnect(interaction: discord.Interaction, status: app_commands.Choice[str]):
    get_user_settings(interaction.user.id)["alert_disconnect"] = (status.value == "on")
    await interaction.response.send_message("退出するときにお知らせするね！" if status.value == "on" else "静かに切断するね！", ephemeral=True)

@bot.tree.command(name="help", description="コマンド一覧を表示")
async def help_command(interaction: discord.Interaction):
    help_text = (
        "**✨ ぼくが使えるコマンド一覧 ✨**\n\n"
        "⏰ **タイマーのセット**\n"
        "`/at_time` ･･･ 指定した時刻（例：23:30）にばいばいするよ！\n"
        "`/in_time` ･･･ 指定した時間（分）のあとにばいばいするよ！\n\n"
        "🔍 **かくにん・キャンセル**\n"
        "`/check` ･･･ 今セットされている予定を確認するよ！\n"
        "`/cancel` ･･･ セットしたばいばいの予定をとりやめるよ！\n\n"
        "🔔 **通知のオン・オフ**\n"
        "`/alert_5` ･･･ 5分前通知のON/OFFを選べるよ！\n"
        "`/alert_1` ･･･ 1分前通知のON/OFFを選べるよ！\n"
        "`/alert_disconnect` ･･･ 退出時メッセージのON/OFFを選べるよ！\n\n"
        "`/help` ･･･ 今見ているこのメッセージを表示するよ！"
    )
    await interaction.response.send_message(help_text, ephemeral=True)

# --- Render(無料枠)で動かすためのWebサーバー設定 ---
app = Flask(__name__)
@app.route('/')
def home():
    return "Bot is running!"

def run_web():
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

# スレッドとしてWebサーバーを起動
Thread(target=run_web).start()
# ------------------------------------------------

bot.run(os.getenv('DISCORD_TOKEN'))