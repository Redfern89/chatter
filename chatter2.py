#!/usr/bin/env python3

import asyncio
import time
import struct
import uuid

from PyQt5.QtWidgets import (
	QAbstractItemView, QLabel, QMainWindow, QStyledItemDelegate, QTableView, QTextEdit, QVBoxLayout, QHBoxLayout, QPushButton, 
	QMessageBox, QApplication, QWidget, QStatusBar, QDialog, QListView, QLineEdit
)
from PyQt5.QtGui import QFont, QPalette, QPixmap, QStandardItemModel, QStandardItem, QIcon, QPainter, QColor, QTextCursor, QTextCharFormat
from PyQt5.QtCore import Q_ARG, QMetaObject, QEvent, Qt, QSize, QItemSelection, QTimer, pyqtSlot, pyqtSignal

from PyQt5.QtCore import Qt
from qasync import QEventLoop
from datetime import datetime
from misc import Settings
from _proto import Proto, ChatMessage

import traceback

class InputField(QTextEdit):
	enterPressed = pyqtSignal()

	def keyPressEvent(self, event):
		if event.key() in (Qt.Key_Return, Qt.Key_Enter):
			if not (event.modifiers() & Qt.ShiftModifier):
				self.enterPressed.emit()
				return
		super().keyPressEvent(event)

class CustomChatterLogger(QTextEdit):
	focused = pyqtSignal()

	def focusInEvent(self, e):
		self.focused.emit()
		return super().focusInEvent(e)
	
class UserColorDelegate(QStyledItemDelegate):
	def __init__(self, parent=None):
		super().__init__(parent)

	def initStyleOption(self, option, index):
		super().initStyleOption(option, index)
		color = index.data(Qt.UserRole)
		status = index.data(Qt.UserRole + 1)

		font = QFont("Courier New", 10)
		font.setBold(True)
		if status == "OFFLINE":
			font.setStrikeOut(True)
			color = "#888888"
		
		option.font = font
		
		if color:
			option.palette.setColor(QPalette.Text, QColor(color))

class Chatter(QMainWindow):
	def __init__(self):
		super().__init__()
		self.users = {}
		self.Settings = Settings()
		
		self.reader = None
		self.writer = None
		self.alive_task = None
		self.listen_task = None
		self.get_users_task = None
		self.connected = False
		self.typing = False
		self.listen_thread = None
		self.editing_block = None
		self.uuid = bytes.fromhex(self.Settings.get('uuid', None))

		if self.uuid is None:
			self.Settings.set('uuid', uuid.uuid4().hex)
			self.uuid = bytes.fromhex(self.Settings.get('uuid', None))

		self.msg_uuid = uuid.uuid4().bytes

		self.server_ip = self.Settings.get('server_ip', '127.0.0.1')
		self.server_port = self.Settings.get('server_port', 9022)
		self.color = self.Settings.get('color', "#5e0008")
		self.nickname = self.Settings.get('nickname', "nickname")
		self.status = self.Settings.get('status', "status")

		self.init_ui()

	def init_ui(self):
		self.setWindowTitle("Chatter")
		self.setGeometry(180, 200, 1200, 600)
		
		self.central_widget = QWidget()
		self.setCentralWidget(self.central_widget)

		self.main_layout = QHBoxLayout()
		self.central_widget.setLayout(self.main_layout)
		self.main_layout.setContentsMargins(0, 0, 0, 0)

		# === LEFT: чат ===
		self.chatter_layout = QVBoxLayout()

		self.ChatterLog = CustomChatterLogger()
		self.ChatterLog.setReadOnly(True)

		self.input_field = InputField()
		self.input_field.enterPressed.connect(self.on_enter)
		self.input_field.textChanged.connect(self.on_text)
		self.input_field.setFixedHeight(0)

		self.chatter_layout.addWidget(self.ChatterLog)
		self.chatter_layout.addWidget(self.input_field)
		self.chatter_layout.setContentsMargins(0, 0, 0, 0)

		self.chatter_widget = QWidget()
		self.chatter_widget.setLayout(self.chatter_layout)

		# === RIGHT: таблица пользователей ===
		self.users_table = QTableView()
		self.users_table.setEditTriggers(QAbstractItemView.NoEditTriggers)

		self.users_table_model = QStandardItemModel()
		self.users_table_model.setHorizontalHeaderLabels(['Nickname', 'Status'])
		self.users_table.setModel(self.users_table_model)

		self.users_table.horizontalHeader().setStretchLastSection(True)
		self.users_table.setShowGrid(False)
		self.users_table.verticalHeader().setVisible(False)
		self.users_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
		self.users_table.setIconSize(QSize(24, 24))
		self.users_table.setItemDelegateForColumn(0, UserColorDelegate(self.users_table))

		self.users_table.setColumnWidth(0, 150)
		
		# === Добавление в layout с пропорцией ===
		self.main_layout.addWidget(self.chatter_widget, 7)  # 70%
		self.main_layout.addWidget(self.users_table, 3)     # 30%

		# === Фокус ===
		self.input_field.setFocus()
		self.ChatterLog.focused.connect(lambda: self.input_field.setFocus())

	async def im_alive_task(self):
		while True:
			#await self.send(Proto.build_alive_message(self.color, self.nickname, self.status))
			await self.send(Proto.build_alive_packet(
				uuid=self.uuid,
				color=self.color,
				nickname=self.nickname,
				status=self.status
			))
			await asyncio.sleep(5)

	async def get_users(self):
		while True:
			await self.send(Proto.build_get_users())
			await asyncio.sleep(1)

	@pyqtSlot(bytes, bytes, str)
	def _update_live_chat(self, uuid, msg_id, msg):
		doc = self.ChatterLog.document()
		text = f"{self.users[uuid]['nickname']}: {msg}"

		user = self.users[uuid]
		prev_msg_id = user.get('msg_id')
		block_index = user.get('editing_block')

		if prev_msg_id != msg_id or block_index is None:
			block_index = doc.blockCount()
			self.ChatterLog.append(text)

			user['editing_block'] = block_index
			user['msg_id'] = msg_id

			block = doc.findBlockByLineNumber(block_index)
		else:
			block = doc.findBlockByLineNumber(block_index)

		cursor = QTextCursor(block)
		cursor.select(QTextCursor.LineUnderCursor)
		cursor.removeSelectedText()
		cursor.insertText(text)

		cursor = QTextCursor(block)
		cursor.select(QTextCursor.LineUnderCursor)
		
		color = self.users[uuid]['color']
		fmt = QTextCharFormat()
		fmt.setForeground(QColor(color))
		fmt.setFont(QFont("Courier New", 10, QFont.Bold))

		cursor.setCharFormat(fmt)

	def safe_live_update(self, uuid, msg_id, msg):
		QMetaObject.invokeMethod(self, "_update_live_chat", Qt.QueuedConnection,
			Q_ARG(bytes, uuid),
			Q_ARG(bytes, msg_id),
			Q_ARG(str, msg)
		)

	@pyqtSlot(str, str, str)
	def _add_user(self, color, nickname, status):
		nick_item = QStandardItem(QIcon('user.png'), nickname)
		nick_item.setData(color, Qt.UserRole)

		self.users_table_model.appendRow([
			nick_item,
			QStandardItem(status)
		])

	def safe_add_user(self, color, nickname, status):
		QMetaObject.invokeMethod(self, "_add_user", Qt.QueuedConnection,
			Q_ARG(str, color),
			Q_ARG(str, nickname),
			Q_ARG(str, status)
		)
	
	@pyqtSlot(str, str, str)
	def _update_user(self, nickname, color, status):
		for row in range(self.users_table_model.rowCount()):
			if self.users_table_model.item(row, 0).text() == nickname:
				self.users_table_model.setItem(row, 1, QStandardItem(status))
				self.users_table_model.item(row, 0).setData(color, Qt.UserRole)
				break

	def safe_update_user(self, nickname, color, status):
		QMetaObject.invokeMethod(self, "_update_user", Qt.QueuedConnection,
			Q_ARG(str, nickname),
			Q_ARG(str, color),
			Q_ARG(str, status)
		)

	def on_text(self):
		text = self.input_field.toPlainText()
		asyncio.create_task(self.send(Proto.build_chat_message(
			msg_id=self.msg_uuid,
			uuid=self.uuid,
			msg=text
		)))

	def on_enter(self):
		self.msg_uuid = uuid.uuid4().bytes
		self.input_field.clear()

	def start_session_tasks(self):
		if self.listen_task is None or self.listen_task.done():
			self.listen_task = asyncio.create_task(self.listen())

		if self.alive_task is None or self.alive_task.done():
			self.alive_task = asyncio.create_task(self.im_alive_task())

		if self.get_users_task is None or self.get_users_task.done():
			self.get_users_task = asyncio.create_task(self.get_users())

	async def connection_monitor(self):
		while True:
			if (
				not self.connected
				or self.writer is None
				or self.writer.is_closing()
			):
				try:
					await self.stop_tasks()
					await self.cleanup()
					await self.connect()
					self.start_session_tasks()

					self.connected = True

					print("[+] Connected")

				except Exception as e:
					print(e)
					print("[!] Server unavailable. retrying...")

			await asyncio.sleep(2)

	async def stop_tasks(self):
		tasks = []

		if self.listen_task:
			self.listen_task.cancel()
			tasks.append(self.listen_task)

		if self.alive_task:
			self.alive_task.cancel()
			tasks.append(self.alive_task)

		if self.get_users_task:
			self.get_users_task.cancel()
			tasks.append(self.get_users_task)

		self.listen_task = None
		self.alive_task = None
		self.get_users_task = None

		await asyncio.gather(*tasks, return_exceptions=True)

	async def cleanup(self):
		if self.writer:
			try:
				self.writer.close()
				await self.writer.wait_closed()
			except Exception as e:
				print("close error:", e)

		self.writer = None
		self.reader = None

	async def connect(self):
		self.reader, self.writer = await asyncio.open_connection(self.server_ip, self.server_port)

	async def packet_handler(self, pkt):
		packet = Proto.unpack_packet(pkt)

		if packet.pkt_type == Proto.TYPE_USERS_LIST:
			users = Proto.parse_users_list(data=packet.payload)

			for user in users:
				if user.uuid not in self.users:
					udata = {
						'uuid': user.uuid,
						'color': user.color,
						'nickname': user.nickname,
						'status': user.status,
						'time': user.time,
						'msg_id': None,
						'editing_block': None
					}
					self.users[user.uuid] = udata
					self.safe_add_user(user.color, user.nickname, user.status)

		if packet.pkt_type == Proto.TYPE_CHAT_BROADCAST_MESSAGE:
			message = Proto.parse_chat_message(packet.payload)
			if message.uuid in self.users:
				self.safe_live_update(message.uuid, message.msg_id, message.msg)


	async def listen(self):
		buffer = b''

		try:
			while True:
				data = await self.reader.read(1024)
				if not data:
					break
				
				buffer += data

				while True:
					if len(buffer) < 2:
						break

					body_len = struct.unpack("!H", buffer[:2])[0]
					full_len = 2 + body_len

					if full_len > 65535:
						buffer = b''
						break

					if len(buffer) < full_len:
						break

					pkt = buffer[2:full_len]
					buffer = buffer[full_len:]

					await self.packet_handler(pkt)

					#print(Proto.unpack_packet(pkt))
					#print("")
				
		except asyncio.CancelledError:
			return

		except Exception as e:
			traceback.print_exc()
			print("Error in listen:", e)

		finally:
			self.connected = False

	async def send(self, data: bytes):
		try:
			if not self.writer or self.writer.is_closing():
				return
		
			self.writer.write(data)
			await self.writer.drain()
		except Exception as e:
			print("Error in send:", e)

if __name__ == "__main__":
	app = QApplication([])

	loop = QEventLoop(app)
	asyncio.set_event_loop(loop)

	window = Chatter()
	window.show()

	loop.create_task(window.connection_monitor())
	
	with loop:
		loop.run_forever()