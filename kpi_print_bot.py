#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
from threading import Thread

import string
import random

import logging
import mysql.connector
import datetime
import telegram
from telegram.ext import Updater
from telegram.ext import CommandHandler
from telegram.ext import MessageHandler
from telegram.ext import Filters
from telegram.ext import MessageQueue

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
					level=logging.INFO)
logger = logging.getLogger(__name__)

working_directory = os.path.dirname(os.path.realpath(__file__))
credentials = dict()
try:
	f = open(working_directory+"/bot_credentials.txt", "r")
except:
	logger.warning('bot_credentials.txt cannot be opened!')
with f:
	for line in f:
		line = line.rstrip().split('=')
		credentials[line[0]] = line[1]
	f.close()

bot_db = mysql.connector.connect(
	host = "127.0.0.1",
	user = credentials['db_user'],
	passwd = credentials['db_password'],
	database = credentials['db_name']
)
db_cursor = bot_db.cursor()

WELCOME_MSG =	('Здравствуйте.\n')
WELCOME_2_MSG =	('Рад видеть вас снова.\n')
HELP_MSG = ('Отправьте мне файл чтобы заказать печать\n'+
			'/help - показать это сообщение\n'+
			'/check <номер заказа> - проверить статус\n'+
			'/cancel <номер заказа> - отменить заказ')
ALLOWED_MIMES = [
	'application/msword',
	'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
	'application/vnd.ms-excel',
	'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
	'application/vnd.ms-powerpoint',
	'application/vnd.openxmlformats-officedocument.presentationml.presentation',
	'application/pdf',
	'application/rtf',
	'text/richtext'
]
ORDER_FAIL_MIME = ( 'К сожалению этот тип файлов не может быть распечатан.\n'+
					'Поддерживаемые типы: doc, docx, xls, xlsx, ppt, pptx, pdf, rtf, rtx')
ORDER_FAIL_PICTURE ='К сожалению картинки не печатаем.'
ORDER_WAIT_1 = 'Сохраняем файл...'
ORDER_WAIT_2 = 'Файл получен.'
ORDER_SUCCESS = (	'Ваш заказ принят.\n'+
					'Номер заказа: ```%s```\n'+
					'Используйте его при оплате, получении или отмене заказа.\n'+
					'Заказ можно отменить с помощью /cancel <номер заказа>')
CHECK_FAIL = 'Такого номера нет в базе данных.'
CHECK_SUCCESS = 'Статус заказа: *%s*.' # может ещё добавить "дополнительный комментарий" от принимающего заказ?
CANCEL_FAIL = 'Невозможно отменить заказ: *%s*'
CANCEL_SUCCESS_PAID = 'Заказ отменён: *%s*.'
CANCEL_SUCCESS = 'Заказ отменён.%s'
ECHO_FAIL = [	'Я бот у меня лапки.',
				'Я не эксперт в этой области.',
				'Полное непонимание.',
				'Шмыг',
				'Дежурный придёт — там разберёмся.',
				'Это вам не это!'
]

def start(bot, context, user_data):
	db_cursor.execute("SELECT * FROM users WHERE user_id=%s", (str(context.message.from_user.id), ))
	db_result = db_cursor.fetchall()

	info = context.message.from_user

	if(len(db_result) == 0): # new user
		db_cursor.execute(
			"INSERT INTO users (user_id, chat_id, username, full_name, n_orders) VALUES (%s, %s, %s, %s, %s)",
			(str(info.id), str(context.message.chat_id), info.username, info.first_name+' '+info.last_name, 0)
		)
		bot_db.commit()


		bot.send_message(chat_id=context.message.chat_id, text=WELCOME_MSG)
		
		logging.info("start: User "+str([str(info.id), info.username, info.first_name+' '+info.last_name])+" was added")
	else: #existing user
		bot.send_message(chat_id=context.message.chat_id, text=WELCOME_2_MSG)
		logging.info("start: User "+str([str(info.id), info.username, info.first_name+' '+info.last_name])+" was encountered")

	bot.send_message(chat_id=context.message.chat_id, text=HELP_MSG)

def order(bot, context):
	# print(context.message.document);
	doc_info = context.message.document;
	msg_info = context.message.from_user

	# print(doc_info.file_name)
	# exit()

	if(doc_info.mime_type in ALLOWED_MIMES):
		ref_num = '';
		while True:
			ref_num = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(6))
			db_cursor.execute("SELECT * FROM orders WHERE order_reference=%s", (ref_num, ))
			db_result = db_cursor.fetchall()
			if(len(db_result) == 0):
				break

		file_id = doc_info.file_id
		dl_file_path = working_directory+'/files/'+ref_num+'-'+doc_info.file_name
		dl_file_name = ref_num+'-'+doc_info.file_name
		print(dl_file_path.encode('utf-8'))

		bot.send_message(
			chat_id=context.message.chat_id,
			text=ORDER_WAIT_1,
			parse_mode=telegram.ParseMode.MARKDOWN
		)

		bot.get_file(file_id).download(dl_file_path.encode('utf-8'))

		bot.send_message(
			chat_id=context.message.chat_id,
			text=ORDER_WAIT_2,
			parse_mode=telegram.ParseMode.MARKDOWN
		)

		db_cursor.execute(
			"INSERT INTO orders (ordered_by, order_reference, file_name, file_id, status) VALUES (%s, %s, %s, %s, %s)",
			(str(msg_info.id), ref_num, dl_file_name.encode('utf-8'), file_id, 'created')
		)
		bot_db.commit()

		logging.info("order: Order "+str([str(msg_info.id), ref_num, doc_info.file_name, doc_info.file_id])+" was created")

		bot.send_message(
			chat_id=context.message.chat_id,
			text=(ORDER_SUCCESS % ref_num),
			parse_mode=telegram.ParseMode.MARKDOWN
		)
	else:
		logging.info("order: File type not supported "+str(doc_info.file_name))
		bot.send_message(chat_id=context.message.chat_id, text=ORDER_FAIL_MIME)

def check(bot, context, user_data):
	input_str = context.message.text.split(' ')
	for i in range(0, len(input_str)):
		input_str[i] = ''.join(c for c in input_str[i] if c.isalnum())
	print(input_str)

	if(len(input_str) >= 2):
		ref_num = input_str[1]
		db_cursor.execute("SELECT status FROM orders WHERE order_reference=%s", (ref_num, ))
		db_result = db_cursor.fetchall()
		if(len(db_result) != 0):
			status = 'глюк';
			if   db_result[0][0] == 'created':
				status = 'создан, не оплачен'
			elif db_result[0][0] == 'paid':
				status = 'оплачен'
			elif db_result[0][0] == 'queued':
				status = 'в очереди на печать'
			elif db_result[0][0] == 'printed':
				status = 'готов к получению'
			elif db_result[0][0] == 'finished':
				status = 'завершён'
			elif db_result[0][0] == 'cancelled':
				status = 'отменён'

			bot.send_message(
				chat_id=context.message.chat_id,
				text=(CHECK_SUCCESS % status),
				parse_mode=telegram.ParseMode.MARKDOWN
			)
		else:
			bot.send_message(
				chat_id=context.message.chat_id,
				text=CHECK_FAIL,
				parse_mode=telegram.ParseMode.MARKDOWN
			)
	else:
		bot.send_message(
			chat_id=context.message.chat_id,
			text=")=",
			parse_mode=telegram.ParseMode.MARKDOWN
		)


def cancel(bot, context, user_data):
	input_str = context.message.text.split(' ')
	for i in range(0, len(input_str)):
		input_str[i] = ''.join(c for c in input_str[i] if c.isalnum())
	print(input_str)

	if(len(input_str) >= 2):
		ref_num = input_str[1]
		db_cursor.execute("SELECT status FROM orders WHERE order_reference=%s", (ref_num, ))
		db_result = db_cursor.fetchall()
		if(len(db_result) != 0):
			CANCEL_ACTION = ''
			status = 'глюк';

			if   db_result[0][0] == 'created':
				status = ' '
				CANCEL_ACTION = CANCEL_SUCCESS
				db_cursor.execute(
					"UPDATE orders SET status=%s, date_cancelled=NOW() WHERE order_reference=%s",
					('cancelled', ref_num)
				)
				bot_db.commit()
			elif db_result[0][0] == 'paid':
				status = 'заказ отменён, не забудьте забрать деньги'
				CANCEL_ACTION = CANCEL_SUCCESS_PAID
			elif db_result[0][0] == 'queued':
				status = 'заказ уже в очереди на печать'
				CANCEL_ACTION = CANCEL_FAIL
			elif db_result[0][0] == 'printed':
				status = 'заказ уже распечатан'
				CANCEL_ACTION = CANCEL_FAIL
			elif db_result[0][0] == 'finished':
				status = 'заказ уже завершён'
				CANCEL_ACTION = CANCEL_FAIL
			elif db_result[0][0] == 'cancelled':
				status = 'заказ уже отменён'
				CANCEL_ACTION = CANCEL_FAIL
				

			bot.send_message(
				chat_id=context.message.chat_id,
				text=(CANCEL_ACTION % status),
				parse_mode=telegram.ParseMode.MARKDOWN
			)
		else:
			bot.send_message(
				chat_id=context.message.chat_id,
				text=CHECK_FAIL,
				parse_mode=telegram.ParseMode.MARKDOWN
			)
	else:
		bot.send_message(
			chat_id=context.message.chat_id,
			text=")=",
			parse_mode=telegram.ParseMode.MARKDOWN
		)

def help(bot, context):
	bot.send_message(chat_id=context.message.chat_id, text=HELP_MSG)

def echo(bot, context, user_data):
	
	while True:
		line = random.randint(0, len(ECHO_FAIL)-1)
		if('echo_line_num' in user_data):
			if(line != user_data['echo_line_num']):
				user_data['echo_line_num'] = line
				break
		else:
			user_data['echo_line_num'] = 0
			line = 0
			break
		
	bot.send_message(chat_id=context.message.chat_id, text=ECHO_FAIL[line])


def error(bot, context, wut):
	"""Log Errors caused by Updates."""
	print(wut)
	logger.warning('Update "%s" caused error "%s"', bot, context.error)

def main():
	"""Start the bot."""
	updater = Updater(credentials['token'])

	# Get the dispatcher to register handlers
	dp = updater.dispatcher

	dp.add_handler(CommandHandler("start", start, pass_user_data=True))
	dp.add_handler(CommandHandler("check", check, pass_user_data=True))
	dp.add_handler(CommandHandler("cancel", cancel, pass_user_data=True))
	dp.add_handler(CommandHandler("help", help))
	dp.add_handler(MessageHandler(Filters.document | (Filters.forwarded & Filters.document), order));

	def stop_and_restart():
		updater.stop()
		os.execl(sys.executable, sys.executable, *sys.argv)
	def restart(bot, context):
		context.message.reply_text('Bot is restarting...')
		logging.info("Bot is restarting")
		Thread(target=stop_and_restart).start()
	dp.add_handler(CommandHandler('r', restart, filters=Filters.user(username='@deiskos')))

	# on noncommand i.e message - echo the message on Telegram
	dp.add_handler(MessageHandler(Filters.text, echo, pass_user_data=True))

	# log all errors
	dp.add_error_handler(error)

	# Start the Bot
	updater.start_polling(poll_interval=0.1, bootstrap_retries=-1, timeout=1.0)

	logging.info("main: Bot started")

	# Run the bot until you press Ctrl-C or the process receives SIGINT,
	# SIGTERM or SIGABRT. This should be used most of the time, since
	# start_polling() is non-blocking and will stop the bot gracefully.
	updater.idle()


if __name__ == '__main__':
	main()

