#!/usr/bin/env python3
import asyncio
import signal
import struct
from _proto import Proto

class AsyncBroadcastServer:
	def __init__(self, host="0.0.0.0", port=9022, buffer_size=1024):
		self.host = host
		self.port = port
		self.buffer_size = buffer_size

		self.server = None
		self.clients = set()
		self.stop_event = asyncio.Event()

		self.users = {}

	async def process_packet(self, pkt, writer):
		packet = Proto.unpack_packet(pkt)

		if packet.pkt_type == Proto.TYPE_CHAT_BROADCAST_MESSAGE:
			for client in list(self.clients):
				try:
					client.write(Proto.make_packet(Proto.TYPE_CHAT_BROADCAST_MESSAGE, packet.payload))
				except Exception:
					pass

			await asyncio.gather(
				*(c.drain() for c in list(self.clients)),
				return_exceptions=True
			)

		if packet.pkt_type == Proto.TYPE_ALIVE:
			user, _ = Proto.parse_user_data(packet.payload)
			
			if user.uuid not in self.users:
				udata = {
					'color': user.color,
					'nickname': user.nickname,
					'status': user.status,
					'time': user.time
				}
				self.users[user.uuid] = udata
			else:
				self.users[user.uuid]['color'] = user.color
				self.users[user.uuid]['nickname'] = user.nickname
				self.users[user.uuid]['status'] = user.status
				self.users[user.uuid]['time'] = user.time

		if packet.pkt_type == Proto.TYPE_GET_USERS:
			#print(writer.get_extra_info("peername"))
			writer.write(Proto.build_users_list(self.users))
			await writer.drain()

	async def handle_client(self, reader, writer):
		addr = writer.get_extra_info("peername")
		buffer = b''
		self.clients.add(writer)
		print(f"[+] connect: {addr}")

		try:
			while True:
				data = await reader.read(self.buffer_size)
				if not data:
					break

				buffer += data

				while True:
					if len(buffer) < 2:
						break

					body_len = struct.unpack("!H", buffer[:2])[0]
					full_len = 2 + body_len

					if len(buffer) < full_len:
						break

					packet = buffer[2:full_len]
					buffer = buffer[full_len:]

					await self.process_packet(packet, writer)

		finally:
			print(f"[-] disconnect: {addr}")

			if writer in self.clients:
				self.clients.remove(writer)

			writer.close()
			await writer.wait_closed()

	def _on_stop_signal(self):
		print("\n[!] stop signal received")
		self.stop_event.set()

	async def start(self):
		self.server = await asyncio.start_server(
			self.handle_client,
			self.host,
			self.port
		)

		print(f"[+] server started on {self.host}:{self.port}")

		loop = asyncio.get_running_loop()
		loop.add_signal_handler(signal.SIGINT, self._on_stop_signal)
		loop.add_signal_handler(signal.SIGTERM, self._on_stop_signal)

		async with self.server:
			await self.stop_event.wait()

		await self.shutdown()

	async def shutdown(self):
		print("[*] shutting down server...")

		if self.server:
			self.server.close()
			await self.server.wait_closed()

		# закрытие клиентов
		for client in list(self.clients):
			try:
				client.close()
			except Exception:
				pass

		await asyncio.gather(
			*(c.wait_closed() for c in self.clients),
			return_exceptions=True
		)

		self.clients.clear()

		print("[+] bye")


if __name__ == "__main__":
	server = AsyncBroadcastServer()
	asyncio.run(server.start())