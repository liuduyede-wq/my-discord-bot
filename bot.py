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
        user_settings[user_id] = {"alert_5": True, "alert_1": True}
    return user_settings[user_id]

def get_alert_text(settings):
    a5 = settings["alert_5"]
    a1 = settings["alert_1"]
    if a5 and a1: return "(5分前と1分前に教えるね！)"
    elif a5: return "(5分前に教えるね！)"
    elif a1: return "(1分前に教えるね！)"
    else: return "(ぼく静かにしてる！)"

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
    settings = get_user_settings(user_id)
    try:
        target_time = datetime.now() + timedelta(seconds=total_seconds)
        if total_seconds > 300:
            await asyncio.sleep(total_seconds - 300)
            if settings["alert_5"] and interaction.user.voice:
                await interaction.followup.send(f"{interaction.user.mention} あと5分でばいばいの時間だよ！準備して！")
        
        now = datetime.now()
        remaining = (target_time - now).total_seconds()
        if remaining > 60:
            await asyncio.sleep(remaining - 60)
            if settings["alert_1"] and interaction.user.voice:
                await interaction.followup.send(f"{interaction.user.mention} あと1分でばいばいの時間だよ！みんなにばいばいして！")

        now = datetime.now()
        remaining = (target_time - now).total_seconds()
        if remaining > 0: await asyncio.sleep(remaining)
            
        if interaction.user.voice:
            await interaction.user.move_to(None)
            await interaction.followup.send(f"{interaction.user.mention} {end_message}")
    except asyncio.CancelledError:
        pass
    finally:
        if user_id in active_timers: del active_timers[user_id]

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
    if interaction.user.id in active_timers:
        await interaction.response.send_message(f"**{active_timers[interaction.user.id]['target_time'].strftime('%H:%M')}**にばいばいする予定だよ！", ephemeral=True)
    else:
        await interaction.response.send_message("みんなとずっと一緒にいる予定だよ！", ephemeral=True)

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

@bot.tree.command(name="help", description="コマンド一覧を表示")
async def help_command(interaction: discord.Interaction):
    await interaction.response.send_message("**✨ ぼくが使えるコマンド一覧 ✨**\n`/at_time` `/in_time` ･･･ タイマーセット\n`/check` ･･･ 予定の確認\n`/cancel` ･･･ キャンセル\n`/alert_5` `/alert_1` ･･･ 通知設定", ephemeral=True)

app = Flask(__name__)
@app.route('/')
def home():
    return "Bot is running!"

def run_web():
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

# スレッドとしてWebサーバーを起動
Thread(target=run_web).start()
# --- ここまで追加 ---

bot.run(os.getenv('DISCORD_TOKEN'))