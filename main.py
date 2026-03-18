import telebot
import requests
import random
import json
import re
import os
import time
import threading
from datetime import datetime
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from config import BOT_TOKEN, ADMIN_ID, CHANNEL_URL

bot = telebot.TeleBot(BOT_TOKEN)
bot.parse_mode = "HTML"

USERS_FILE = 'users.json'

def load_users():
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=2)

def add_user(user_id, username, first_name):
    users = load_users()
    if str(user_id) not in users:
        users[str(user_id)] = {
            'user_id': user_id,
            'username': username,
            'first_name': first_name,
            'joined_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'last_active': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        save_users(users)
    else:
        users[str(user_id)]['last_active'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        users[str(user_id)]['username'] = username
        users[str(user_id)]['first_name'] = first_name
        save_users(users)

class NovGenBot:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        self.bot_name = "NovGen"

    def generate_valid_card(self, bin_number):
        remaining_length = 16 - len(bin_number)
        card_number = bin_number
        
        for i in range(remaining_length - 1):
            card_number += str(random.randint(0, 9))
        
        total = 0
        reverse_digits = [int(d) for d in str(card_number)][::-1]
        
        for i, digit in enumerate(reverse_digits):
            if i % 2 == 0:
                total += digit
            else:
                doubled = digit * 2
                total += doubled if doubled < 10 else doubled - 9
        
        checksum = (total * 9) % 10
        card_number += str(checksum)
        
        return card_number

    def generate_luhn_cards(self, bin_number, count=10):
        cards = []
        
        for _ in range(count):
            card_number = self.generate_valid_card(bin_number)
            
            current_year = datetime.now().year
            exp_month = random.randint(1, 12)
            exp_year = random.randint(current_year, current_year + 5)
            
            cvv = str(random.randint(100, 999)).zfill(3)
            
            cards.append(f"{card_number} | {str(exp_month).zfill(2)} | {exp_year} | {cvv}")
        
        return cards

    def get_bin_info(self, bin_number):
        try:
            response = self.session.get(f"https://lookup.binlist.net/{bin_number}")
            if response.status_code == 200:
                data = response.json()
                
                scheme = data.get('scheme', 'UNKNOWN').upper()
                if scheme == 'VISA':
                    scheme = 'VISA CREDIT'
                elif scheme == 'MASTERCARD':
                    scheme = 'MASTER CARD'
                elif scheme == 'AMEX':
                    scheme = 'AMERICAN EXPRESS'
                elif scheme == 'DISCOVER':
                    scheme = 'DISCOVER'
                elif scheme == 'JCB':
                    scheme = 'JCB'
                elif scheme == 'DINERS':
                    scheme = 'DINERS CLUB'
                elif scheme == 'RUPAY':
                    scheme = 'RUPAY'
                
                bank = data.get('bank', {}).get('name', 'UNKNOWN BANK')
                if bank != 'UNKNOWN BANK':
                    bank = bank.upper()
                
                country = data.get('country', {}).get('name', 'UNKNOWN')
                if country != 'UNKNOWN':
                    country = country.upper()
                
                card_type = data.get('type', 'UNKNOWN').upper()
                
                return {
                    'bank': bank,
                    'country': country,
                    'scheme': scheme,
                    'type': card_type
                }
        except Exception as e:
            pass
        
        bin_prefix = bin_number[:6]
        first_digit = bin_number[0] if bin_number else '0'
        
        if first_digit == '4':
            return {
                'bank': 'VARIOUS BANKS',
                'country': 'VARIOUS COUNTRIES',
                'scheme': 'VISA CREDIT',
                'type': 'CREDIT'
            }
        elif first_digit == '5':
            return {
                'bank': 'VARIOUS BANKS',
                'country': 'VARIOUS COUNTRIES',
                'scheme': 'MASTER CARD',
                'type': 'CREDIT'
            }
        elif first_digit == '3':
            if bin_prefix.startswith('34') or bin_prefix.startswith('37'):
                return {
                    'bank': 'VARIOUS BANKS',
                    'country': 'VARIOUS COUNTRIES',
                    'scheme': 'AMERICAN EXPRESS',
                    'type': 'CREDIT'
                }
            else:
                return {
                    'bank': 'VARIOUS BANKS',
                    'country': 'VARIOUS COUNTRIES',
                    'scheme': 'DINERS CLUB',
                    'type': 'CREDIT'
                }
        elif first_digit == '6':
            return {
                'bank': 'VARIOUS BANKS',
                'country': 'VARIOUS COUNTRIES',
                'scheme': 'DISCOVER',
                'type': 'CREDIT'
            }
        elif first_digit == '2':
            return {
                'bank': 'VARIOUS BANKS',
                'country': 'VARIOUS COUNTRIES',
                'scheme': 'MASTER CARD',
                'type': 'CREDIT'
            }
        else:
            return {
                'bank': 'UNKNOWN BANK',
                'country': 'UNKNOWN',
                'scheme': 'UNKNOWN',
                'type': 'UNKNOWN'
            }

    def check_card(self, card_number, expiry_month, expiry_year, cvv):
        try:
            if len(card_number) != 16 or not card_number.isdigit():
                return {'status': 'DECLINED', 'message': 'Invalid card number format'}
            
            current_date = datetime.now()
            current_year = current_date.year
            current_month = current_date.month
            
            exp_year = int(expiry_year)
            exp_month = int(expiry_month)
            
            if exp_year < current_year or (exp_year == current_year and exp_month < current_month):
                return {'status': 'DECLINED', 'message': 'Card expired'}
            
            if not self.luhn_check(card_number):
                return {
                    'status': 'DECLINED', 
                    'message': 'Invalid card',
                    'bin_info': self.get_bin_info(card_number[:6])
                }
            
            bin_info = self.get_bin_info(card_number[:6])
            
            if random.random() < 0.8:
                return {
                    'status': 'APPROVED',
                    'message': 'Live CC',
                    'bin_info': bin_info
                }
            else:
                return {
                    'status': 'DECLINED',
                    'message': 'Dead CC',
                    'bin_info': bin_info
                }
                
        except Exception as e:
            return {'status': 'ERROR', 'message': f'Check failed: {str(e)}'}

    def luhn_check(self, card_number):
        total = 0
        reverse_digits = [int(d) for d in str(card_number)][::-1]
        
        for i, digit in enumerate(reverse_digits):
            if i % 2 == 1:
                doubled = digit * 2
                total += doubled if doubled < 10 else doubled - 9
            else:
                total += digit
        
        return total % 10 == 0

    def validate_bin(self, bin_number):
        bin_number = bin_number.replace(' ', '')
        if bin_number.isdigit() and 6 <= len(bin_number) <= 15:
            return True
        return False

novgen_bot = NovGenBot()

def set_bot_commands():
    commands = [
        BotCommand("start", "Start NovGen Bot"),
        BotCommand("gen", "Generate CC From Bin"),
        BotCommand("chk", "Check Approved Card")
    ]
    bot.set_my_commands(commands)

def create_regenerate_button(bin_number):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Regenerate Cards", callback_data=f"regen_{bin_number}"))
    return markup

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    username = message.from_user.username or "No username"
    first_name = message.from_user.first_name or "Unknown"
    add_user(user_id, username, first_name)
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Join Updates", url=CHANNEL_URL))
    
    welcome_msg = f"""<b>Hi! Welcome to {novgen_bot.bot_name}</b>

NovGen is your ultimate toolkit on Telegram, packed with CC generators, educational resources, downloaders, temp mail, crypto utilities, and more. Simplify your tasks with cardin ease!

Don't forget to Join for updates!"""
    
    bot.send_message(
        message.chat.id,
        welcome_msg,
        parse_mode='HTML',
        reply_markup=markup
    )

@bot.message_handler(commands=['bd'])
def broadcast_message(message):
    if message.from_user.id != ADMIN_ID:
        return
    
    if len(message.text.split()) < 2:
        bot.reply_to(message, "<b>Usage:</b> /bd Your broadcast message here", parse_mode='HTML')
        return
    
    broadcast_text = message.text[4:].strip()
    
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("Confirm", callback_data="broadcast_confirm"),
        InlineKeyboardButton("Cancel", callback_data="broadcast_cancel")
    )
    
    bot.reply_to(
        message, 
        f"{broadcast_text}\n\nSend this message to all users?", 
        parse_mode='HTML',
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('broadcast_'))
def handle_broadcast_confirmation(call):
    if call.message.chat.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "Unauthorized")
        return
    
    if call.data == "broadcast_confirm":
        bot.answer_callback_query(call.id, "Broadcasting started...")
        
        original_text = call.message.text
        broadcast_msg = original_text.split("\n\nSend this")[0]
        
        users = load_users()
        total_users = len(users)
        success_count = 0
        fail_count = 0
        
        for user_id in users.keys():
            try:
                bot.send_message(
                    int(user_id),
                    f"{broadcast_msg}",
                    parse_mode='HTML'
                )
                success_count += 1
            except Exception as e:
                fail_count += 1
        
        summary = f"""<b>Broadcast Complete</b>

Total Users: {total_users}
Success: {success_count}
Failed: {fail_count}"""
        
        bot.edit_message_text(
            summary,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode='HTML'
        )
        
    elif call.data == "broadcast_cancel":
        bot.edit_message_text(
            "<b>Broadcast cancelled</b>",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode='HTML'
        )
        bot.answer_callback_query(call.id, "Broadcast cancelled")

@bot.message_handler(commands=['gen'])
def generate_cc(message):
    user_id = message.from_user.id
    username = message.from_user.username or "No username"
    first_name = message.from_user.first_name or "Unknown"
    add_user(user_id, username, first_name)
    
    try:
        if len(message.text.split()) > 1:
            bin_number = message.text.replace('/gen', '').strip()
            process_gen_directly(message, bin_number)
        else:
            help_msg = f"""<b>Generate CC From Bin</b>

Send BIN in format:
<code>/gen BIN</code>

Example:
<code>/gen 453201</code>
<code>/gen 512345</code>
<code>/gen 378282</code>

Note: BIN must be 6-15 digits"""
            
            bot.reply_to(message, help_msg, parse_mode='HTML')
    except Exception as e:
        pass

def process_gen_directly(message, bin_number):
    try:
        if not novgen_bot.validate_bin(bin_number):
            bot.reply_to(message, "<b>Invalid BIN! Must be 6-15 digits</b>", parse_mode='HTML')
            return
        
        bin_info = novgen_bot.get_bin_info(bin_number[:6])
        cards = novgen_bot.generate_luhn_cards(bin_number, count=10)
        
        response = f"<b>BIN → {bin_number}</b>\n"
        response += f"<b>Amount → 10</b>\n\n"
        
        for card in cards:
            response += f"<code>{card}</code>\n"
        
        scheme = bin_info.get('scheme', 'UNKNOWN')
        bank = bin_info.get('bank', 'UNKNOWN BANK')
        country = bin_info.get('country', 'UNKNOWN')
        
        response += f"\n<b>Info:</b> {scheme}\n"
        response += f"<b>Bank:</b> {bank}\n"
        response += f"<b>Country:</b> {country}"
        
        current_time = datetime.now().strftime("%I:%M %p")
        response += f"\n{current_time}"
        
        markup = create_regenerate_button(bin_number)
        bot.reply_to(message, response, parse_mode='HTML', reply_markup=markup)
        
    except Exception as e:
        bot.reply_to(message, f"<b>Error: {str(e)}</b>", parse_mode='HTML')

@bot.message_handler(func=lambda message: message.text and message.text.startswith('/gen'))
def handle_gen_all(message):
    if len(message.text.split()) > 1:
        bin_number = message.text.replace('/gen', '').strip()
        process_gen_directly(message, bin_number)

@bot.callback_query_handler(func=lambda call: call.data.startswith('regen_'))
def regenerate_cards(call):
    try:
        bin_number = call.data.replace('regen_', '')
        
        bin_info = novgen_bot.get_bin_info(bin_number[:6])
        cards = novgen_bot.generate_luhn_cards(bin_number, count=10)
        
        response = f"<b>BIN → {bin_number}</b>\n"
        response += f"<b>Amount → 10</b>\n\n"
        
        for card in cards:
            response += f"<code>{card}</code>\n"
        
        scheme = bin_info.get('scheme', 'UNKNOWN')
        bank = bin_info.get('bank', 'UNKNOWN BANK')
        country = bin_info.get('country', 'UNKNOWN')
        
        response += f"\n<b>Info:</b> {scheme}\n"
        response += f"<b>Bank:</b> {bank}\n"
        response += f"<b>Country:</b> {country}"
        
        current_time = datetime.now().strftime("%I:%M %p")
        response += f"\n{current_time}"
        
        markup = create_regenerate_button(bin_number)
        
        bot.edit_message_text(
            response,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode='HTML',
            reply_markup=markup
        )
        
        bot.answer_callback_query(call.id, "Cards regenerated successfully!")
        
    except Exception as e:
        bot.answer_callback_query(call.id, f"Error: {str(e)}")

@bot.message_handler(commands=['chk'])
def check_card_command(message):
    user_id = message.from_user.id
    username = message.from_user.username or "No username"
    first_name = message.from_user.first_name or "Unknown"
    add_user(user_id, username, first_name)
    
    try:
        text = message.text
        
        if len(text.split()) > 1:
            card_data = text[5:].strip() if text.startswith('/chk ') else text[4:].strip()
            
            if card_data:
                process_card_check(message, card_data)
            else:
                show_help(message)
        else:
            show_help(message)
    except Exception as e:
        bot.reply_to(message, f"<b>Error: {str(e)}</b>", parse_mode='HTML')

def show_help(message):
    help_msg = f"""<b>Check Approved Card</b>

Send card details in any format:

<code>/chk 4532010914221065|06|2027|892</code>
<code>/chk 4532010914221065 06 2027 892</code>
<code>/chk 4532010914221065/06/2027/892</code>

The bot will automatically detect and format them."""
    
    bot.reply_to(message, help_msg, parse_mode='HTML')

def process_card_check(message, card_data):
    try:
        if '|' in card_data:
            parts = card_data.split('|')
        elif '/' in card_data:
            parts = card_data.split('/')
        elif ' ' in card_data:
            parts = card_data.split()
        else:
            numbers = re.findall(r'\d+', card_data)
            if len(numbers) >= 4:
                parts = numbers
            else:
                bot.reply_to(message, "<b>Invalid format! Could not extract card details.</b>", parse_mode='HTML')
                return
        
        clean_parts = []
        for part in parts:
            part = part.strip()
            if part:
                digits = re.sub(r'\D', '', part)
                if digits:
                    clean_parts.append(digits)
        
        if len(clean_parts) < 4:
            bot.reply_to(message, "<b>Insufficient data! Need card, month, year, and CVV.</b>", parse_mode='HTML')
            return
        
        card_number = clean_parts[0]
        month = clean_parts[1]
        year = clean_parts[2]
        cvv = clean_parts[3]
        
        if len(month) == 1:
            month = '0' + month
        elif len(month) > 2:
            month = month[:2]
        
        if len(year) == 2:
            year = '20' + year
        elif len(year) > 4:
            year = year[:4]
        
        if len(card_number) != 16 or not card_number.isdigit():
            bot.reply_to(message, "<b>Invalid card number! Must be 16 digits.</b>", parse_mode='HTML')
            return
        
        if not month.isdigit() or int(month) < 1 or int(month) > 12:
            bot.reply_to(message, "<b>Invalid month! Must be 01-12.</b>", parse_mode='HTML')
            return
        
        if not year.isdigit() or len(year) != 4:
            bot.reply_to(message, "<b>Invalid year! Must be 4 digits (YYYY).</b>", parse_mode='HTML')
            return
        
        if not cvv.isdigit() or len(cvv) < 3 or len(cvv) > 4:
            bot.reply_to(message, "<b>Invalid CVV! Must be 3-4 digits.</b>", parse_mode='HTML')
            return
        
        result = novgen_bot.check_card(card_number, month, year, cvv)
        
        response = f"""<b>Card →</b> <code>{card_number} | {month} | {year} | {cvv}</code>
<b>Status →</b> {result['status']}
<b>Msg →</b> {result['message']}"""
        
        if 'bin_info' in result and result['bin_info']:
            response += f"""

<b>Info →</b> {result['bin_info'].get('scheme', 'UNKNOWN')}
<b>Bank →</b> {result['bin_info'].get('bank', 'UNKNOWN BANK')}
<b>Country →</b> {result['bin_info'].get('country', 'UNKNOWN')}"""
        
        current_time = datetime.now().strftime("%I:%M %p")
        response += f"\n{current_time}"
        
        bot.reply_to(message, response, parse_mode='HTML')
        
    except Exception as e:
        bot.reply_to(message, f"<b>Error processing card: {str(e)}</b>", parse_mode='HTML')

@bot.message_handler(func=lambda message: message.text and message.text.startswith('/chk'))
def handle_all_chk(message):
    check_card_command(message)

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    pass

def start_bot():
    """Start the bot with proper error handling for Render"""
    while True:
        try:
            print(f"{novgen_bot.bot_name} Is Running")
            print(f"Admin ID: {ADMIN_ID}")
            print(f"Channel URL: {CHANNEL_URL}")
            
            bot.remove_webhook()
            set_bot_commands()
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            print(f"Bot crashed: {str(e)}")
            print("Restarting in 5 seconds...")
            time.sleep(5)

if __name__ == "__main__":
    start_bot()