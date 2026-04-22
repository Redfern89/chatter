#!/usr/bin/env python3

import socket
import threading
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

from datetime import datetime
import traceback

from misc import Settings
from proto import Proto

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
		
		self.typing = False
		self.listen_thread = None
		self.editing_block = None
		self.multicast_group = '239.255.0.1'
		self.msg_uuid = uuid.uuid4().bytes

		self.Settings = Settings()

		self.port = self.Settings.get('port', 9022)
		self.color = self.Settings.get('color', "#5e0008")
		self.nickname = self.Settings.get('nickname', "nickname")
		self.status = self.Settings.get('status', "status")

		self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		self.sock.settimeout(1)
		self.sock.bind(('', self.port))
		local_ip = socket.inet_aton("0.0.0.0")  # важно!
		self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, local_ip)
		self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
		self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
		self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024)  # 1 МБ буфер

		group = socket.inet_aton(self.multicast_group)
		mreq = struct.pack('4s4s', group, local_ip)
		self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

		self.start_listening()
		self.init_ui()

		self.im_alive_timer = QTimer()
		self.im_alive_timer.setInterval(1000)
		self.im_alive_timer.timeout.connect(self.im_alive)
		self.im_alive_timer.start()

		self.check_online_timer = QTimer()
		self.check_online_timer.setInterval(1000)
		self.check_online_timer.timeout.connect(self.check_online)
		self.check_online_timer.start()

		self.chack_typing_timer = QTimer()
		self.chack_typing_timer.setInterval(1000)
		self.chack_typing_timer.setSingleShot(True)
		self.chack_typing_timer.timeout.connect(self._reset_typing_flag)

	def init_ui(self):
		self.setWindowTitle("Chatter TCP/IP UDP")
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
		self.input_field.enterPressed.connect(self.on_new_line)
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

	def im_alive(self):
		if not self.typing:
			#self.sock.sendto(Proto.build_alive_message(self.color, self.nickname, self.status), (self.multicast_group, self.port))
			self.sock.sendto(Proto.make_chat_new_user(self.color, self.nickname, self.status), (self.multicast_group, self.port))
			pass

	def check_online(self):
		for user_k, user_v in self.users.items():
			user_time = user_v['time']
			now = int(time.time())
			if now - user_time >= 5:
				self.update_user_online_status(user_k, 'OFFLINE')
			else:
				self.update_user_online_status(user_k, 'ONLINE')

	def update_user_online_status(self, nickname, status):
		for row in range(self.users_table_model.rowCount()):
			if self.users_table_model.item(row, 0).text() == nickname:
				self.users_table_model.item(row, 0).setData(status, Qt.UserRole +1)
				break

	def on_new_line(self):
		self.msg_uuid = uuid.uuid4().bytes
		self.input_field.clear()

	def send_message(self, msg):
		self.typing = True
		self.chack_typing_timer.start()

		self.sock.sendto(Proto.make_chat_message(
			uuid=self.msg_uuid,
			color=self.color,
			nickname=self.nickname,
			msg=msg
		), (self.multicast_group, self.port))

	def _reset_typing_flag(self):
		self.typing = False

	def on_text(self):
		text = self.input_field.toPlainText()
		self.send_message(text)

	@pyqtSlot(bytes, str, str, str)
	def _update_live_chat(self, uuid, color, nick, msg):
		if nick not in self.users:
			return

		doc = self.ChatterLog.document()
		text = f'{nick}: {msg}'

		user = self.users[nick]
		prev_uuid = user.get('uuid')
		block_index = user.get('editing_block')

		if prev_uuid != uuid or block_index is None:
			block_index = doc.blockCount()
			self.ChatterLog.append(text)

			user['editing_block'] = block_index
			user['uuid'] = uuid

			block = doc.findBlockByLineNumber(block_index)
		else:
			block = doc.findBlockByLineNumber(block_index)

		cursor = QTextCursor(block)
		cursor.select(QTextCursor.LineUnderCursor)
		cursor.removeSelectedText()
		cursor.insertText(text)

		cursor = QTextCursor(block)
		cursor.select(QTextCursor.LineUnderCursor)

		fmt = QTextCharFormat()
		fmt.setForeground(QColor(color))
		fmt.setFont(QFont("Courier New", 10, QFont.Bold))

		cursor.setCharFormat(fmt)

	def safe_live_update(self, uuid, color, nick, msg):
		QMetaObject.invokeMethod(self, "_update_live_chat", Qt.QueuedConnection,
			Q_ARG(bytes, uuid),
			Q_ARG(str, color),
			Q_ARG(str, nick),
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

	def start_listening(self):
		def run():
			while True:
				buffer = bytearray()

				try:
					data, addr = self.sock.recvfrom(1024)
					buffer.extend(data)
					
					while True:
						if len(buffer) < 2:
							break
						
						body_len = struct.unpack('!H', buffer[:2])[0]
						full_len = 2 + body_len

						if len(buffer) < full_len:
							break

						packet = bytes(buffer[2:full_len])
						buffer = buffer[full_len:]

						self.handle_packet(packet)

				except socket.timeout:
					continue
				except Exception as e:
					traceback.print_exc() 
					print(f"[!] Network error: {e}")
		
		self.listen_thread = threading.Thread(target=run, daemon=True)
		self.listen_thread.start()

	def handle_packet(self, data: bytes):
		data_type = struct.unpack('!B', data[:1])[0]
		if data_type == Proto.TYPE_CHAT_BROADCAST_MESSAGE:
			chatmessage = Proto.parse_chat_message(data)

			if chatmessage.nickname not in self.users:
				self.users[chatmessage.nickname] = {
					'color': chatmessage.color,
					'nickname': chatmessage.nickname,
					'time': int(time.time()),
					'editing_block': None,
					'uuid': None
				}

			self.safe_live_update(chatmessage.uuid, chatmessage.color, chatmessage.nickname, chatmessage.msg)
		
		if data_type == Proto.TYPE_CHAT_NEW_USER:
			user = Proto.parse_chat_new_user(data)

			if user.nickname not in self.users:
				self.users[user.nickname] = {
					'color': user.color,
					'nickname': user.nickname,
					'time': int(time.time()),
					'editing_block': None,
					'uuid': None
				}
				self.safe_add_user(user.color, user.nickname, user.status)
			else:
				self.users[user.nickname]['time'] = int(time.time())
				self.safe_update_user(user.nickname, user.color, user.status)

if __name__ == "__main__":
	app = QApplication([])
	window = Chatter()
	window.show()
	app.exec_()