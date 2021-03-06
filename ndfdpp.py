import xml.dom.minidom
import MySQLdb
import urllib
import urllib2
import sys
import time
import json
import pickle
import argparse
import datetime
import ConfigParser
from itertools import izip

parser = argparse.ArgumentParser(description='Gather NDFD data and put it into MySQL')
parser.add_argument('-c', dest='conffile')
parser.add_argument('-r', dest='retry', action='store_true')
parser.add_argument('-d', dest='debug', action='store_true')
parser.add_argument('-u', dest='url',   action='store_true')
parser.add_argument('-i', dest='insertonly', action='store_true')
args = parser.parse_args()

# CONFIGURATION START
# List of NDFD Element eg. ['maxt', 'mint'] Leave [] for ALL variables
# http://www.nws.noaa.gov/xml/docs/elementInputNames.php
ndfd_elements = ['mint', 'maxt', 'dew', 'rh', 'pop12', 'qpf', 'sky', 'wspd'] 

# Either time-series or glance
ndfd_product  = 'time-series'

# List of latitude and longitude tuples. MUST BE PROVIDED
coop_id        = [21]
locations      = [(29.80, -82.41)]
#coop_id       = [490, 350, 360, 330, 290, 251, 111]
#locations     = [(27.22, -81.84), (27.76, -82.22), (28.02, -82.23), (28.10, -81.71), (29.22, -81.45), (28.75, -82.30), (28.02, -82.11)]

# Database configuration
if args.conffile:
	conf_file = args.conffile
else:
	conf_file = 'config'

config = ConfigParser.SafeConfigParser(defaults={'host':'localhost', 'port':3306, 'user':'user', 'password':'pass', 'database':'database', 'desttable':'forecast_data'})
config.read(conf_file)
db_host       = config.get('mysql', 'host')
db_port       = config.getint('mysql', 'port')
db_user       = config.get('mysql', 'user')
db_pass       = config.get('mysql', 'password')
db_database   = config.get('mysql', 'database')
data_table    = config.get('mysql', 'desttable')

# CONFIGURATION END - PLEASE DO NOT EDIT PAST THIS POINT
if len(locations) == 0:
	db = MySQLdb.connect(host=db_host, port=db_port, user=db_user, passwd=db_pass, db=db_database)
	dc = db.cursor(MySQLdb.cursors.DictCursor)
	dc.execute("SELECT id, lat, lon FROM stations")
	results = dc.fetchall()
	for entry in results:
		coop_id.append(entry["id"])
		locations.append((entry["lat"], entry["lon"]))
	db.commit()
	dc.close()
	db.close()

oldpickledata = {}
runtime       = datetime.datetime.now()

try:
	cache_file = open('sqlcache.db', 'rb')
	oldpickledata = pickle.load(cache_file)
	cache_file.close()
except IOError:
	pass

if args.retry:
	if 'rerun' in oldpickledata:
		if not oldpickledata['rerun']:
			if args.debug:
				print "No need to re-run."
			sys.exit(0)
		

if 'data' in oldpickledata:
	oldpickledata = oldpickledata['data']

timemap   = {}
datamap   = {}
finaldata = {}

ndfd_url = "http://www.weather.gov/forecasts/xml/sample_products/browser_interface/ndfdXMLclient.php"

def gen_loc(head, tail):
	if(isinstance(head, tuple)):
		hlat, hlon = head
		tlat, tlon = tail
		return "%s,%s %s,%s" % (hlat, hlon, tlat, tlon)
	else:
		lat, lon = tail
		return "%s %s,%s" % (head, lat, lon)

def build_timemap(time):
	key = time.parentNode.firstChild.nextSibling.firstChild.nodeValue.strip()
	val = time.firstChild.nodeValue.strip()
	if key not in timemap:
		timemap[key] = list()
	timemap[key].append(val)

def build_datamap(data):
	apploc = data.parentNode.parentNode.getAttribute('applicable-location')
	apploc = filter(type(apploc).isdigit, apploc)
	loc = "%s" % str(location[int(apploc)-1])
	parent = data.parentNode.nodeName
	vartype   = '-'.join(data.parentNode.getAttribute('type').split())
	parent = '-'.join((vartype, parent))
	key    = data.parentNode.getAttribute('time-layout')
	val    = data.firstChild.nodeValue.strip()
	if loc not in datamap:
		datamap[loc] = {}
	if parent not in datamap[loc]:
		datamap[loc][parent] = {'key':key, 'vals':[]}
	datamap[loc][parent]['vals'].append(val)

def build_finaldata(loc):
	loc_index = locations.index(tuple(map(float, loc[1:-1].split(','))))
	locale  = str(coop_id[loc_index])
	for varname, data in datamap[loc].iteritems():
		vardata = data['vals']
		timestamps = timemap[data['key']]
		for t,v in izip(timestamps, vardata):
			ts = t
			if locale not in finaldata:
				finaldata[locale] = {}
			if ts not in finaldata[locale]:
				finaldata[locale][ts] = {}
			finaldata[locale][ts][varname] = v


loc_lists = []
id_lists  = []
i = len( locations ) / 150
while i >= 0:
	loc_lists.append( locations[i*150:i*150+150] )
	id_lists.append( coop_id[i*150:i*150+150] )
	i = i - 1

loc_lists.reverse()
for location, st_id in izip(loc_lists, id_lists):
	ndfd_url = "http://www.weather.gov/forecasts/xml/sample_products/browser_interface/ndfdXMLclient.php"

	if len(location) == 0:
		err =  "ERROR: Invalid configuration: locations"
		sys.exit(err)
	elif len(location) == 1:
		ndfd_loc = "%.2f,%.2f" % location[0]
	else:
		ndfd_loc = urllib.quote(reduce(gen_loc, location))

	ndfd_el = '&'.join(map(lambda e: "%s=%s" % (e,e), ndfd_elements))
	ndfd_url = "%s?listLatLon=%s&product=%s&%s" % (ndfd_url, ndfd_loc, ndfd_product, ndfd_el)

	if args.url:
		print ndfd_url
		continue
	# Get the url and parse the information from it (using minidom)
	response = urllib2.urlopen(ndfd_url)
	# Send the information to the parser
	xmlret = xml.dom.minidom.parse(response)
	response.close()
	times = xmlret.getElementsByTagName('start-valid-time')
	if len(times) == 0:
		oldpickledata['data'] = oldpickledata
		oldpickledata['rerun'] = True
		pickle_file = open('sqlcache.db', 'wb')
		pickle.dump(oldpickledata, pickle_file, -1)
		pickle_file.close()
		sys.exit("NDFD REST Service not responding at %s" % runtime.isoformat())

	values = xmlret.getElementsByTagName('value')

	# Building the values in-memory via maps
	map(build_timemap, times)
	map(build_datamap, values)
	map(build_finaldata, datamap)

if args.url:
	sys.exit(0)

# Datbase interaction
sqlinsertdata = []
sqlupdatedata = []
newpickledata = {}

# Need the database object to cleanup the json object
db = MySQLdb.connect(host=db_host, port=db_port, user=db_user, passwd=db_pass, db=db_database)
for station_id, station_data in finaldata.iteritems():
	if station_id not in newpickledata:
		newpickledata[str(station_id)] = []
	for ts, time_data in finaldata[station_id].iteritems():
		newpickledata[str(station_id)].append(ts)
		time_data['timestamp'] = ts
		data = json.dumps(time_data)
		mts = str(datetime.datetime.strptime(ts[:-6], "%Y-%m-%dT%H:%M:%S"))
		if len(oldpickledata) > 0 and (str(station_id) in oldpickledata):
			if ts in oldpickledata[str(station_id)]:
				if args.insertonly:
					sqlupdatedata.append((str(station_id), mts, db.string_literal(data)))
				else:
					sqlupdatedata.append((db.string_literal(data), str(station_id), mts))
			else:
				sqlinsertdata.append((str(station_id), mts, db.string_literal(data)))
		else:
			sqlinsertdata.append((str(station_id), mts, db.string_literal(data)))

c  = db.cursor()
if len(sqlinsertdata) > 0:
	if args.debug:
		print "Inserting %i row(s)" % len(sqlinsertdata)
	c.executemany("""INSERT INTO """+data_table+"""(coop_id, forecast_ts, data) VALUES (%s, %s, %s)""", sqlinsertdata)
	db.commit()
if len(sqlupdatedata) > 0:
	if args.insertonly:
		if args.debug:
			print "Inserting %i row(s)" % len(sqlupdatedata)
		c.executemany("""INSERT INTO """+data_table+"""(coop_id, forecast_ts, data) VALUES (%s, %s, %s)""", sqlupdatedata)
	else:
		if args.debug:
			print "Updating %i row(s)" % len(sqlupdatedata)
		c.executemany("""UPDATE """+data_table+""" SET data=%s WHERE coop_id=%s AND forecast_ts=%s""", sqlupdatedata)
	db.commit()
c.close()
db.close()

newpickledata['data'] = newpickledata
newpickledata['rerun'] = False

pickle_file = open('sqlcache.db', 'wb')
pickle.dump(newpickledata, pickle_file, -1)
pickle_file.close()
