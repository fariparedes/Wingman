import requests
import json, re
import xml.etree.ElementTree as ET
from collections import defaultdict
import sys, getopt
import websockets, asyncio
import uuid
import webbrowser
import traceback
import hashlib
from random import shuffle

#Program settings
USERNAME = ""
PASSWORD = ""
CHARACTER = ""
CHANNELS = []
HOST = "chat.f-list.net"
PORT = 9722
SERVICE_NAME = "Wingman"
SERVICE_VERSION = 2.2
SUGGESTIONS_TO_MAKE = 10
RANDOMIZE_SUGGESTIONS = False
REJECT_ODD_GENDERS = False
STRICT_MATCHING = False
QUALITY_CUTOFF = 80
DISALLOWED_COCK_SHAPES = []

#Character grading settings
GRADE_WEIGHTS = {'profile play' : 0.01,
		'bad species' : 0.04,
		'bbcode abuse' : 0.05,
		'punctuation' : 0.05,
		'name punctuation' : 0.05,
		'no images' : 0.1,
		'literacy' : 0.125,
		'custom kinks' : 0.125,
		'description length' : 0.15,
		'kink matching' : 0.3
		}
BAD_SPECIES_LIST = []
GOOD_SPECIES_LIST = []
AUTOFAIL_DESCRIPTION_LIST = ['murr', 'yiff', ' owo ', ' uwu ', ' ._.', ' >.<', ' :3', ' >:3', ' >_>', '^^', '^,~']
BBCODE_TAG_LIST = {'[b]' : 4,
		   '[big]' : 2,
		   '[indent]' : 4,
		   '[collapse=' : 4,
		   '[color=' : 8
		   }
EXPECTED_NUMBER_CUSTOM_KINKS = 5
EXPECTED_MAXIMUM_CUSTOM_KINKS = 100
EXPECTED_DESCRIPTION_LENGTH = 2500
EXPECTED_MATCHING_KINKS = 0.75
PROBABLE_WIP_DESCRIPTION_LENGTH = 750
LINEBREAK_PER_CHARACTERS = 500
SPELLING_ERROR_PER_CHARACTERS = 2500
UNDERKINKING_BONUS_FLOOR = 20
OVERKINKING_PENALTY_FLOOR = 200
OVERKINKING_MODIFIER = 5
MAX_EXTRA_CREDIT = 1.2
PICTURE_IS_WORTH = 1000
INDECISIVENESS_FLOOR = 70
FORMATTING_ALLOWANCE = 500
DEFAULT_AVATAR_CHECKSUM = b'`\xa0\xd4/\x92\xdcn\xaf?8\x99-o\xc8(\xd9\x02\x9a[G'

#Caches
TICKET = None
INFO_LIST = None
MAP_LIST = None
SPELLCHECK = None
CHARACTER_LIST = set()

def post_json(url, forms = {}):
	succeeded = False
	while not succeeded:
		try:
			resp = requests.post(url, data = forms, timeout=10)
			succeeded = True
		except Exception as e:
			print_error(e)
	return resp.json()
	
def request_avatar(character):
	succeeded = False
	while not succeeded:
		try:
			resp = requests.get("https://static.f-list.net/images/avatar/{}.png".format(character.lower()), timeout=10)
			succeeded = True
		except Exception as e:
			print_error(e)
	return hashlib.sha1(resp.content)
	
def request_ticket(bookmarks = None):
	forms = {"account" : USERNAME, "password" : PASSWORD}
	ticket_json = post_json('https://www.f-list.net/json/getApiTicket.php', forms)
	if bookmarks != None:
		bookmarks |= set([x['name'] for x in ticket_json['bookmarks']] + [x['source_name'] for x in ticket_json['friends']] + ticket_json['characters'])
	if ticket_json['error'] == '':
		return ticket_json['ticket']
	else:
		print_error(ticket_json['error'])
		return 0

def print_error(text):
	print('\nError: ',text)
	try:
		if 'ticket' in text:
			global TICKET
			TICKET = None
	except TypeError:
		return
		#that wasn't iterable
		
def print_progress_bar(current,total,description):
	total_width = 60
	num_dashes = int(total_width*(current/total))
	num_spaces = int(total_width*((total-current)/total))
	while num_dashes+num_spaces < total_width:
		num_dashes += 1
	sys.stdout.write("\r[" + "="*num_dashes + " "*num_spaces + "]  " + description)
	sys.stdout.flush()

def ticket(bookmarks = None):
	global TICKET
	if TICKET == None:
		TICKET = request_ticket(bookmarks)
	return TICKET

def request_character(name, ticket):
	forms = {"account" : USERNAME, "ticket" : ticket, "name" : name}
	character_json = post_json('https://www.f-list.net/json/api/character-data.php', forms)
	return character_json

def cap_grade(num_points, max_points):
	if max_points <= 0:
		return 0
	grade = num_points/max_points
	overflow_grade = grade - 1
	if overflow_grade > 0:
		grade = 1
		overflow_grade *= (MAX_EXTRA_CREDIT-1)
		grade += (overflow_grade if overflow_grade < (MAX_EXTRA_CREDIT-1) else (MAX_EXTRA_CREDIT-1))
	return grade

def get_info_by_name(name):
	global INFO_LIST
	if INFO_LIST == None:
		INFO_LIST = post_json('https://www.f-list.net/json/api/info-list.php')
	for _ in range(4):
		for info in INFO_LIST['info'][str(_+(1 if _ < 3 else 2))]['items']:
			if info['name'] == name:
				return str(info['id'])
	return -1

def get_infotag(name):
	global MAP_LIST
	if MAP_LIST == None:
		MAP_LIST = post_json('https://www.f-list.net/json/api/mapping-list.php')
	for tag in MAP_LIST['listitems']:
		if tag['value'] == name:
			return tag['id']
	return -1

def spellcheck_api(text, inline_modifier):
	text = re.sub("[\[].*?[\]]", "", text)
	got_spellcheck = False
	while not got_spellcheck:
		global SPELLCHECK
		SPELLCHECK = requests.post('http://service.afterthedeadline.com/stats', data = {'key' : SERVICE_NAME + str(SERVICE_VERSION) + str(uuid.getnode()), 'data' : text})
		timeout = 0
		if "503 Service Temporarily Unavailable" in SPELLCHECK.text:
			while timeout < 100:
				timeout += 1
		else:
			got_spellcheck = True
	spellcheck_xml = ET.fromstring(SPELLCHECK.text)
	errors = 0
	for node in spellcheck_xml:
		#print(node[0].text, node[1].text, node[2].text)
		if node[0].text == 'grammar':
			errors += int(node[2].text)*3
		elif node[1].text == 'estimate':
			errors += int(node[2].text)
		elif node[1].text == 'hyphenate':
			errors += int(node[2].text)/2
		elif node[1].text == 'misused words':
			errors += int(node[2].text)/2
		elif node[0].text == 'style' and node[1].text != 'complex phrases':
			errors += int(node[2].text)/4
	length = (len(text)+inline_modifier if len(text)+inline_modifier >= SPELLING_ERROR_PER_CHARACTERS else SPELLING_ERROR_PER_CHARACTERS)
	return length/(1 if errors < 1 else errors)

def get_kinks(json):
	kinks = dict(json['kinks'])
	if len(json['custom_kinks']) > 0:
		check_customs = json['custom_kinks']
		for custom in check_customs.values():
			if len(custom['children']) > 0:
				for child in custom['children']:
					kinks[str(child)] = custom['choice']
	return kinks

def test_orientation_matching(json1, json2):
	if get_info_by_name('Orientation') in json1['infotags'] and get_info_by_name('Orientation') in json2['infotags']:
		if json1['infotags'][get_info_by_name('Orientation')] == get_infotag('Gay') and json2['infotags'][get_info_by_name('Orientation')] == get_infotag('Straight'):
			return False
	elif STRICT_MATCHING:
		return False
	if get_info_by_name('Orientation') in json1['infotags']:
		if json1['infotags'][get_info_by_name('Orientation')] == get_infotag('Gay') and get_info_by_name('Gender') in json1['infotags'] and get_info_by_name('Gender') in json2['infotags'] and\
		     ((json1['infotags'][get_info_by_name('Gender')] == get_infotag('Male') and json2['infotags'][get_info_by_name('Gender')] == get_infotag('Female')) or\
		     (json1['infotags'][get_info_by_name('Gender')] == get_infotag('Female') and json2['infotags'][get_info_by_name('Gender')] == get_infotag('Male'))):
			return False
		elif json1['infotags'][get_info_by_name('Orientation')] == get_infotag('Straight') and get_info_by_name('Gender') in json1['infotags'] and get_info_by_name('Gender') in json2['infotags'] and\
		     json1['infotags'][get_info_by_name('Gender')] == json2['infotags'][get_info_by_name('Gender')]:
			return False
		elif STRICT_MATCHING and json1['infotags'][get_info_by_name('Orientation')] == get_infotag('Bi - male preference') and get_info_by_name('Gender') in json2['infotags'] and json2['infotags'][get_info_by_name('Gender')] == get_infotag('Female'):
			return False
		elif STRICT_MATCHING and json1['infotags'][get_info_by_name('Orientation')] == get_infotag('Bi - female preference') and get_info_by_name('Gender') in json2['infotags'] and json2['infotags'][get_info_by_name('Gender')] == get_infotag('Male'):
			return False
	return True
	
def test_furry_matching(json1, json2):
	if get_info_by_name('Furry preference') in json1['infotags'] and get_info_by_name('Body type') in json2['infotags']:
		if json1['infotags'][get_info_by_name('Furry preference')] == get_infotag('No furry characters, just humans') and json2['infotags'][get_info_by_name('Body type')] == get_infotag('Anthro'):
			return False
		elif json1['infotags'][get_info_by_name('Furry preference')] == get_infotag('No humans, just furry characters') and json2['infotags'][get_info_by_name('Body type')] == get_infotag('Human'):
			return False
		elif STRICT_MATCHING and json1['infotags'][get_info_by_name('Furry preference')] == get_infotag('Humans ok, Furries Preferred') and json2['infotags'][get_info_by_name('Body type')] == get_infotag('Human'):
			return False
		elif STRICT_MATCHING and json1['infotags'][get_info_by_name('Furry preference')] == get_infotag('Furries ok, Humans Preferred') and json2['infotags'][get_info_by_name('Body type')] == get_infotag('Anthro'):
			return False
	elif STRICT_MATCHING:
		return False
	if get_info_by_name('Furry preference') in json1['infotags'] and get_info_by_name('Species') in json2['infotags']:
		if json1['infotags'][get_info_by_name('Furry preference')] == get_infotag('No humans, just furry characters') and json2['infotags'][get_info_by_name('Species')] == "Human":
			return False
		elif STRICT_MATCHING and json1['infotags'][get_info_by_name('Furry preference')] == get_infotag('No furry characters, just humans') and json2['infotags'][get_info_by_name('Species')] != "Human":
			return False
	return True

def test_role_matching(json1, json2):
	if get_info_by_name('Dom/Sub Role') in json1['infotags'] and get_info_by_name('Dom/Sub Role') in json2['infotags']:
		if json1['infotags'][get_info_by_name('Dom/Sub Role')] in [get_infotag('Always submissive'), get_infotag('Usually submissive')] and (json2['infotags'][get_info_by_name('Dom/Sub Role')] in [get_infotag('Always submissive'), get_infotag('Usually submissive')]\
		or (STRICT_MATCHING and not json2['infotags'][get_info_by_name('Dom/Sub Role')] in [get_infotag('Always dominant'), get_infotag('Usually dominant')])):
			return False
		elif json1['infotags'][get_info_by_name('Dom/Sub Role')] in [get_infotag('Always dominant'), get_infotag('Usually dominant')] and (json2['infotags'][get_info_by_name('Dom/Sub Role')] in [get_infotag('Always dominant'), get_infotag('Usually dominant')]\
		or (STRICT_MATCHING and not json2['infotags'][get_info_by_name('Dom/Sub Role')] in [get_infotag('Always submissive'), get_infotag('Usually submissive')])):
			return False
	elif STRICT_MATCHING:
		return False
	return True
	
def grade_character(json, my_json):
	if REJECT_ODD_GENDERS and not get_info_by_name('Gender') in json['infotags']:
		return 0
	elif REJECT_ODD_GENDERS and json['infotags'][get_info_by_name('Gender')] != get_infotag('Male') and\
		   json['infotags'][get_info_by_name('Gender')] != get_infotag('Female'):
		return 0
		
	if not STRICT_MATCHING or get_info_by_name('Orientation') in my_json['infotags']:
		if not test_orientation_matching(json, my_json):
			return 0
		if not test_orientation_matching(my_json, json):
			return 0
	if not STRICT_MATCHING or get_info_by_name('Furry preference') in my_json['infotags']:
		if not test_furry_matching(json, my_json):
			return 0
		if not test_furry_matching(my_json, json):
			return 0
	if not STRICT_MATCHING or get_info_by_name('Dom/Sub Role') in my_json['infotags']:
		if not test_role_matching(json, my_json):
			return 0
		if not test_role_matching(my_json, json):
			return 0
		
	if get_info_by_name('Orientation') in my_json['infotags']:
		if my_json['infotags'][get_info_by_name('Orientation')] == get_infotag('Bi - female preference') and get_info_by_name('Gender') in json['infotags'] and\
		     json['infotags'][get_info_by_name('Gender')] == get_infotag('Male'):
			return 0 
		elif my_json['infotags'][get_info_by_name('Orientation')] == get_infotag('Bi - male preference') and get_info_by_name('Gender') in json['infotags'] and\
		     json['infotags'][get_info_by_name('Gender')] == get_infotag('Female'):
			return 0
			
	if len(DISALLOWED_COCK_SHAPES) > 0 and get_info_by_name('Cock shape') in json['infotags'] and (not get_info_by_name('Gender') in json['infotags'] or json['infotags'][get_info_by_name('Gender')] != get_infotag('Female')):
		for shape in DISALLOWED_COCK_SHAPES:
			if json['infotags'][get_info_by_name('Cock shape')] == get_infotag(shape):
				return 0
		
	return do_grade_character(json, my_json)
	
	

def do_grade_character(json, my_json):
	if json['error'] != '':
		print_error(json['error'])
		return -1
	if my_json['error'] != '':
		print_error(my_json['error'])
		return -1
		
			
	grades = defaultdict(int)
	grades['bad species'] = GRADE_WEIGHTS['bad species']
	if get_info_by_name('Species') in json['infotags']:
		for species in BAD_SPECIES_LIST:
			if species.upper() in json['infotags'][get_info_by_name('Species')].upper():
				grades['bad species'] = 0
		for species in GOOD_SPECIES_LIST:
			if species.upper() in json['infotags'][get_info_by_name('Species')].upper():
				grades['bad species'] = MAX_EXTRA_CREDIT * GRADE_WEIGHTS['bad species']
	else:
	     grades['bad species'] = grades['bad species']/2
	     
	name = json['name']
	
	grades['name punctuation'] = (0 if ' ' in name or '-' in name or '_' in name or name.capitalize() != name else 1) * GRADE_WEIGHTS['name punctuation']
	
	images = json['images']
	grades['no images'] = (0 if len(images) == 0 else 1) * GRADE_WEIGHTS['no images']
	
	custom_kinks = json['custom_kinks']
	grades['custom kinks'] = cap_grade(len(custom_kinks), EXPECTED_NUMBER_CUSTOM_KINKS) * GRADE_WEIGHTS['custom kinks']
	
	description = json['description']
	
	description_notags = re.sub("[\[].*?[\]]", "", description)
	for autofail_word in AUTOFAIL_DESCRIPTION_LIST:
		if autofail_word.upper() in description.upper():
			#print(autofail_word)
			return 0
	tags_overused = 1.5
	for tag, max_use in BBCODE_TAG_LIST.items():
		used = description.upper().count(tag.upper())
		if used > max_use:
			tags_overused -= (used-max_use)/(max_use*2)
	if tags_overused < 0:
		tags_overused = 0
	grades['bbcode abuse'] = cap_grade(tags_overused, 1) * GRADE_WEIGHTS['bbcode abuse']
	
	grades['punctuation'] = (0 if ('!!' in description or '??' in description) else 1) * GRADE_WEIGHTS['punctuation']
	
	grades['profile play'] = (0 if '[icon]'.upper() in description.upper() or '[user]'.upper() in description.upper() else 1) * GRADE_WEIGHTS['profile play']

	description_length = len(description_notags)
	inline_modifier = (description.count('[img') + (len(images)/5 if description_length < EXPECTED_DESCRIPTION_LENGTH and description_length > PROBABLE_WIP_DESCRIPTION_LENGTH else 0) + len(re.findall(re.compile("\[url=.*?(.png|.jpg|.jpeg|.gif)\]"), description))) * PICTURE_IS_WORTH
	formatting_allowance = ((description.count('[img') + description.count('[size') + description.count('[color') + description.count('[b') + description.count('[color') + description.count('[indent')) * (PICTURE_IS_WORTH/2)) if description_length < EXPECTED_DESCRIPTION_LENGTH and description_length > PROBABLE_WIP_DESCRIPTION_LENGTH else ((description.count('[img') + len(re.findall(re.compile("\[url=.*?(.png|.jpg|.jpeg|.gif)\]"), description))) * PICTURE_IS_WORTH)
	linebreaks_allowed = 2*((description_length+(formatting_allowance/2))/LINEBREAK_PER_CHARACTERS)
	linebreaks = re.sub("[\[].*?[\]]", "", re.sub("(\[small\]|\[center\]|\[indent\]|\[quote\]|\r\n\[url).*?(\[\/small\]|\[\/center\]|\[\/indent\]|\[\/quote\]|\[\/url\])","",description, flags = re.DOTALL)).count('\n')
	linebreak_to_text_ratio = linebreaks_allowed / (1 if linebreaks < 1 else linebreaks)
	if linebreak_to_text_ratio > MAX_EXTRA_CREDIT:
		linebreak_to_text_ratio = MAX_EXTRA_CREDIT
	grades['description length'] = cap_grade(description_length+inline_modifier, EXPECTED_DESCRIPTION_LENGTH) * linebreak_to_text_ratio * GRADE_WEIGHTS['description length']
	if grades['description length'] > 1.2*GRADE_WEIGHTS['description length']:
		grades['description length'] = 1.2*GRADE_WEIGHTS['description length']

	if (description_length+inline_modifier) >= PROBABLE_WIP_DESCRIPTION_LENGTH:
		grades['literacy'] = cap_grade(spellcheck_api(description_notags, inline_modifier), SPELLING_ERROR_PER_CHARACTERS) * GRADE_WEIGHTS['literacy']
	else:
		grades['literacy'] = cap_grade(description_length, PROBABLE_WIP_DESCRIPTION_LENGTH) * GRADE_WEIGHTS['literacy']
		
	if grades['description length'] > GRADE_WEIGHTS['description length'] and grades['literacy'] < 0.75 * GRADE_WEIGHTS['literacy']:
		grades['description length'] = GRADE_WEIGHTS['description length']
	
	kinks = get_kinks(json)
	my_kinks = get_kinks(my_json)
	matches = 0
	shared = 0
	#print("{}/{}".format(len(kinks),len(post_json('https://www.f-list.net/json/api/mapping-list.php')['kinks'])))
	if not len(kinks) <= UNDERKINKING_BONUS_FLOOR:
		faves = len([x for x in kinks if kinks[x] == 'fave'])
		for kink, rating in my_kinks.items():
			if kink in kinks and not (kinks[kink] == 'no' and rating == 'no'):
				shared += 1
				if kinks[kink] == rating:
					matches += 1
				elif (rating == 'fave' and kinks[kink] == 'yes') or (rating == 'yes' and kinks[kink] == 'fave'):
					matches += 0.75
				elif (rating == 'maybe' and kinks[kink] == 'yes') or (rating == 'maybe' and kinks[kink] == 'fave'):
					matches += 0.5
				'''elif (rating == 'no' and kinks[kink] == 'fave') or (rating == 'fave' and kinks[kink] == 'no'):
					matches -= 1 * ((len(kinks)/OVERKINKING_PENALTY_FLOOR)*OVERKINKING_MODIFIER if len(kinks) > OVERKINKING_PENALTY_FLOOR else 1)
				elif (rating == 'no' and kinks[kink] == 'yes') or (rating == 'yes' and kinks[kink] == 'no'):
					matches -= 0.5 * ((len(kinks)/OVERKINKING_PENALTY_FLOOR)*OVERKINKING_MODIFIER if len(kinks) > OVERKINKING_PENALTY_FLOOR else 1)'''
		grades['kink matching'] = cap_grade((matches if matches >= 0 else 0), shared * EXPECTED_MATCHING_KINKS) * GRADE_WEIGHTS['kink matching'] * (1 if faves <= INDECISIVENESS_FLOOR else 1/(faves/INDECISIVENESS_FLOOR))
	else:
		normal_grade = cap_grade(len(custom_kinks), 50) * GRADE_WEIGHTS['kink matching']
		grades['kink matching'] =  (normal_grade if len(custom_kinks) <= EXPECTED_MAXIMUM_CUSTOM_KINKS else (normal_grade - (len(custom_kinks)/EXPECTED_MAXIMUM_CUSTOM_KINKS) if normal_grade - (len(custom_kinks)/EXPECTED_MAXIMUM_CUSTOM_KINKS) > 0 else 0))
	total_grade = 0
	for rubric, grade in grades.items():
		#print(rubric + ': ' + str(grade))
		total_grade += grade
	return (0 if total_grade < 0 else total_grade * 100)

async def hello(ticket):
	async with websockets.connect('ws://{0}:{1}'.format(HOST, PORT)) as websocket:
		identify = "IDN {{ \"method\": \"ticket\", \"account\": \"{0}\", \"ticket\": \"{1}\", \"character\": \"{4}\", \"cname\": \"{2}\", \"cversion\": \"{3}\" }}".format(USERNAME, ticket, SERVICE_NAME, SERVICE_VERSION, CHARACTER)
		await websocket.send(identify)
		while True:
			receive = await websocket.recv()
			break
		for channel in CHANNELS:
			join = "JCH {{\"channel\": \"{0}\"}}".format(channel)
			await websocket.send(join)
		received = 0
		while True:
			receive = await websocket.recv()
			'''try:
				non_bmp_map = dict.fromkeys(range(0x10000, sys.maxunicode + 1), 0xfffd)
				print(receive.translate(non_bmp_map))
			finally:
				pass'''
			if receive.startswith('ERR'):
				print_error(json.loads(receive[4:])['message'])
				if 'This command requires that you have logged in.' in receive:
					print('(Sorry about that. Try running again.)')
				if 'Could not locate the requested channel.' in receive:
					print('(Malformed channel name. Check your channel list and try again.)')
					quit()
				if 'You are already in the requested channel.' in receive:
					print('(Duplicate channel name. Check your channel list and try again.)')
					quit()
			if receive.startswith('ICH'):
				global CHARACTER_LIST
				CHARACTER_LIST |= set([list(x.values())[0] for x in json.loads(receive[4:])["users"]])
				websocket.close()
				received += 1
				continue
			if received >= len(CHANNELS):
				return

if __name__ == '__main__':
	bookmarks = set()
	my_character = request_character(CHARACTER, ticket(bookmarks))
	if len(sys.argv) > 1:
		character = request_character(" ".join(sys.argv[1:]), ticket())
		grade = grade_character(character,my_character)
		if grade >= 0:
			print('Grade: ', grade)
	else:
		try:
			asyncio.get_event_loop().run_until_complete(hello(ticket()))
		except websockets.ConnectionClosed:
			print('The connection was closed prematurely.')
			quit()
		print("Successfully grabbed profile list. Preloading the profile data...".format(SERVICE_NAME))
		chars = []
		cur_char = 0
		total_chars = len(CHARACTER_LIST)
		blacklist = None
		try:
			with open('blacklist.txt', 'a+') as bl:
				bl.seek(0)
				blacklist = [x.strip() for x in bl.readlines()]
		except IOError:
			pass
		for char in CHARACTER_LIST:
			print_progress_bar(cur_char,total_chars,"Requesting {}".format(char) + " "*17)
			try:
				while True:
					if (blacklist != None and char in blacklist) or request_avatar(char).digest() == DEFAULT_AVATAR_CHECKSUM or char in bookmarks:
						cur_char += 1
						break
					character = request_character(char, ticket())
					if character['error'] == '' and not character['is_self']:
						chars.append(character)
						cur_char += 1
						break
					elif character['error'] == "Invalid ticket.":
						TICKET = None
					else:
						cur_char += 1
						break
			except Exception:
				print("\nCouldn't fetch {0}: \n{1}".format(char,traceback.format_exc()))
				#print(character)
		print_progress_bar(cur_char,total_chars,"Requesting {}...".format(char) + " "*17)
		print("\nAll profiles loaded. {0} is grading them now.".format(SERVICE_NAME))
		graded_characters = defaultdict(int)
		cur_char = 0
		total_chars = len(chars)
		NUM_CHARS = 0
		DISQ_CHARS = 0
		for character in chars:
			name = character['name']
			print_progress_bar(cur_char,total_chars,str(int(DISQ_CHARS/(1 if NUM_CHARS == 0 else NUM_CHARS)*100)) + "% DQ  " + "Grading {}".format(name) + " "*17)
			try:
				num_errors = 0
				while True:
					graded_characters[name] = grade_character(character,my_character)
					if graded_characters[name] >= 0 or num_errors > 10:
						NUM_CHARS += 1
						DISQ_CHARS += (0 if graded_characters[name] > 0 else 1)
						cur_char += 1
						if num_errors > 10:
							print("\nCouldn't grade {0}.".format(name))
						break
					else:
						num_errors += 1
			except Exception:
				print("\nCouldn't grade {0}: \n{1}".format(name,traceback.format_exc()))
				#print(character)
		print_progress_bar(cur_char,total_chars,str(int(DISQ_CHARS/(1 if NUM_CHARS == 0 else NUM_CHARS)*100)) + "% DQ  " + "Grading {}".format(name) + " "*17)
		print()
		top_chars = sorted(graded_characters, key = (lambda x: graded_characters[x]), reverse = True)
		if graded_characters[top_chars[0]] < QUALITY_CUTOFF:
			print("I couldn't find anyone worth your time, {0}. :( Try again later?".format(CHARACTER))
		else:
			cutoff_chars = []
			for char in top_chars:
				if graded_characters[char] >= QUALITY_CUTOFF:
					cutoff_chars.append(char)
			print('\nAll done, {0}. Consider checking out these profiles: '.format(CHARACTER))
			if RANDOMIZE_SUGGESTIONS:
				shuffle(cutoff_chars)
			for _ in range(SUGGESTIONS_TO_MAKE):
				if len(cutoff_chars) > _ :
					top = cutoff_chars[_]
					print('{0} (Grade: {1})'.format(top, graded_characters[top]))
			bl = input('Do you want to review them for your blacklist? (Y/n) ')
			if bl.upper() != 'N' and bl.upper() != 'NO':
					with open('blacklist.txt', 'a+') as blacklist:
							for char in cutoff_chars[:SUGGESTIONS_TO_MAKE]:
									webbrowser.open('https://f-list.net/c/{0}'.format(char),new=2)
									bl = input('Is {0} someone you might ever want to play with? (y/N) '.format(char))
									if bl.upper() != 'Y' and bl.upper() != 'YES':
											blacklist.write('{0}\n'.format(char))
			if len(cutoff_chars) < SUGGESTIONS_TO_MAKE:
				print('Consider setting your QUALITY_CUTOFF configuration a little lower, or trying again during a busier time of day.')
