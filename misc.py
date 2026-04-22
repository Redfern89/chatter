import os
import json

class Settings:
	def __init__(self, filename="settings.json"):
		self.filename = filename
		self.data = self._load()

	def _load(self):
		if os.path.exists(self.filename):
			with open(self.filename, 'r', encoding='utf-8') as f:
				return json.load(f)
		return {}
	
	def save(self):
		with open(self.filename, 'w', encoding='utf-8') as f:
			json.dump(self.data, f, indent=4)
		
	def get(self, key, default):
		return self.data.get(key, default)

	def set(self, key, value):
		self.data[key] = value
		self.save()