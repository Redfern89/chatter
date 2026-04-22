#!/usr/bin/env python3

import asyncio

async def tcp_client():
	reader, writer = await asyncio.open_connection('127.0.0.1', 9000)

	message = b'Hello, bro!'
	print(f'-> отправляем: {message}')

	writer.write(message)
	await writer.drain()  # важно: реально отправляет буфер

	# читаем ответ
	data = await reader.read(1024)
	print(f'<- получили: {data}')

	writer.close()
	await writer.wait_closed()

asyncio.run(tcp_client())