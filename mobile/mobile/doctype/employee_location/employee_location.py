# Copyright (c) 2023, Qunatbit and contributors
# For license information, please see license.txt
import frappe
import requests
import json
from frappe.model.document import Document

class EmployeeLocation(Document):
	def validate(self):
		self.set_map_location()
		self.calculate_distance()

	def set_map_location(self):
		location_list = []
		for location in self.location_table:
			location_list.append([location.longitude, location.latitude])
		map_json = {
			"type": "FeatureCollection",
			"features": [
				{
					"type": "Feature",
					"properties": {},
					"geometry": {
						"type": "LineString",
						"coordinates": location_list,
					},
				},
				{
					"type": "Feature",
					"properties": {},
					"geometry": {
						"type": "Point",
						"coordinates": location_list[0],
					},
				},
			],
		}

		self.my_location = json.dumps(map_json)

	@frappe.whitelist()
	def calculate_distance(self):
		get_length = len(self.location_table)
		if get_length >= 2:
			first_cord = self.get("location_table")[get_length-2]
			second_cord = self.get("location_table")[get_length-1]
			api_key = '1cfcdeaf26352898f9975a577da9fd30'
			url = f"https://apis.mappls.com/advancedmaps/v1/{api_key}/distance_matrix/driving/{first_cord.longitude},{first_cord.latitude};{second_cord.longitude},{second_cord.latitude}?rtype=0&region=IND"

			payload = {}
			headers = {'accept': 'application/json'}

			response = requests.get(url, headers=headers, data=payload)

			if response.status_code == 200:
				response_data = response.json()
				distance = response_data['results']['distances'][0][1]
				self.distance = self.distance +float(distance/1000)
				
