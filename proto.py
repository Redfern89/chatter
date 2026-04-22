from dataclasses import dataclass
import struct

@dataclass
class PacketBase:
	length: int
	pkt_type: int
	payload: bytes

@dataclass
class ChatMessage:
	uuid: bytes
	color: str
	nickname: str
	msg: str

@dataclass
class User:
	color: str
	nickname: str
	status: str

class Proto:

	TYPE_CHAT_BROADCAST_MESSAGE = 1
	TYPE_CHAT_NEW_USER = 2

	@staticmethod
	def make_packet(pkt_type: int, payload: bytes) -> bytes:
		pkt_body = struct.pack("!B", pkt_type) + payload
		return struct.pack("!H", len(pkt_body)) + pkt_body

	@staticmethod
	def pack_str(s: str) -> bytes:
		encoded = s.encode('utf-8')
		return struct.pack("!H", len(encoded)) + encoded

	@staticmethod
	def make_chat_message(uuid: bytes, color: str, nickname: str, msg: str) -> bytes:
		payload = (
			uuid +
			Proto.pack_str(color) +
			Proto.pack_str(nickname) +
			Proto.pack_str(msg)
		)

		return Proto.make_packet(Proto.TYPE_CHAT_BROADCAST_MESSAGE, payload)
	
	@staticmethod
	def make_chat_new_user(color: str, nickname: str, status: str) -> bytes:
		payload = (
			Proto.pack_str(color) +
			Proto.pack_str(nickname) +
			Proto.pack_str(status)
		)

		return Proto.make_packet(Proto.TYPE_CHAT_NEW_USER, payload)
	
	@staticmethod
	def parse_chat_message(data: bytes):
		if len(data) < 3:
			raise ValueError("Data too short to be a valid packet")

		offset = 1 # Skip the type byte
		uuid = data[offset:offset+16]  # 16 bytes for UUID
		offset += 16

		color_len = struct.unpack("!H", data[offset:offset+2])[0]
		offset += 2
		color = data[offset:offset+color_len].decode('utf-8')
		offset += color_len

		nickname_len = struct.unpack("!H", data[offset:offset+2])[0]
		offset += 2
		nickname = data[offset:offset+nickname_len].decode('utf-8')
		offset += nickname_len

		msg_len = struct.unpack("!H", data[offset:offset+2])[0]
		offset += 2
		msg = data[offset:offset+msg_len].decode('utf-8')

		return ChatMessage(
			uuid=uuid,
			color=color,
			nickname=nickname,
			msg=msg
		)
	
	@staticmethod
	def parse_chat_new_user(data: bytes) -> User:
		if len(data) < 3:
			raise ValueError("Data too short to be a valid packet")

		offset = 1 # Skip the type byte
		
		color_len = struct.unpack("!H", data[offset:offset+2])[0]
		offset += 2
		color = data[offset:offset+color_len].decode('utf-8')
		offset += color_len

		nickname_len = struct.unpack("!H", data[offset:offset+2])[0]
		offset += 2
		nickname = data[offset:offset+nickname_len].decode('utf-8')
		offset += nickname_len

		status_len = struct.unpack("!H", data[offset:offset+2])[0]
		offset += 2
		status = data[offset:offset+status_len].decode('utf-8')

		return User(
			color=color,
			nickname=nickname,
			status=status
		)