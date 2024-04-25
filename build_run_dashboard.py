#
# Made by Guillaume HENON
# October 2023
#
import logging,traceback,argparse, configparser
import jinja2
import pandas as pd
from jinja2 import Environment, FileSystemLoader
from logging import raiseExceptions
import os,datetime
import requests
import json
import re
import hashlib
from datetime import datetime
import pytz
#from PIL import Image, ImageDraw, ImageFont
from math import radians, sin, cos

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)) + os.sep)
BASE_DATA_DIR = BASE_DIR + 'data'+ os.sep

ap = argparse.ArgumentParser(description="Script to build run dashboard from ServiceNow and Dynatrace data")
# Add the arguments to the parser
ap.add_argument("-d", "--debug", action="store_true",help="Set debug mode")
ap.add_argument("-r", "--reuse", action="store_true",help="Reuse saved exports")
ap.add_argument("-oa", "--onlyavailability", action="store_true",help="Display only Availability information")
args = ap.parse_args()
isdebug=args.debug

if isdebug:
    loglevel=logging.DEBUG
else:
    loglevel=logging.INFO
if args.reuse:
    REUSE=True
else:
    REUSE=False
if args.onlyavailability:
    OA=True
else:
    OA=False  
    
try:
    logname,ext=os.path.splitext(BASE_DIR+os.path.basename(__file__))
    logname=logname+".log"
    logging.basicConfig(format='%(asctime)s::%(levelname)s::%(message)s', filename=logname, filemode="w", level=loglevel)
except:
    logging.error("error when defining logging")
    
configfile="dynatrace_sanity_checks.ini"
if os.path.isfile(configfile):
    config = configparser.ConfigParser()
    config.read(configfile)
else:
    logging.error("Config file ["+configfile+"] is missing")
    exit()
    
logging.debug(config.sections())
logging.debug(config['DYNATRACE']['URL'])
DYNATRACE_URL=config['DYNATRACE']['URL']
SERVICENOW_URL=config['SERVICENOW']['URL']
TOKEN=config['DYNATRACE']['TOKEN_METRICS']

# Define time zones for cities
time_zones = {
    "New York": "America/New_York",
    "London": "Europe/London",
    "Tokyo": "Asia/Tokyo",
    "Sydney": "Australia/Sydney"
}
#minutes
timerange=240 

def avail_request(l_url):
    
    base_url=l_url
    #build a hash of url to save file
    filehash=int(hashlib.sha256(base_url.encode('utf-8')).hexdigest(), 16) % 10**8
    datafile=BASE_DATA_DIR+"dynatrace_availdata_"+str(filehash)+".json"
    
    
    session = requests.Session()
    session.headers.update({"Accept":"application/json"})
    session.headers.update({"Content-Type":"application/json"})
    session.headers.update({"Authorization": "Api-Token "+TOKEN})
    try:
        if REUSE and os.path.isfile(datafile) :
            logging.debug(datafile+" reused")
            with open(datafile) as f:
                json_data=json.load(f)
        else:
            response = session.get(base_url)
            response.raise_for_status()
            logging.debug("Problem API response: "+str(response.status_code))
            json_data = response.json()
            
            with open(datafile, 'w', encoding='utf-8') as f:
                json.dump(json_data, f, ensure_ascii=False, indent=4)
                    
    except Exception as err:
        logging.error(err)
        logging.error(traceback.format_exc())
        exit()
    return json_data['result'][0]['data']
    
def avail_data_http(l_timerange):
    
    base_url=DYNATRACE_URL+"/api/v2/metrics/query?metricSelector=(builtin:synthetic.http.availability.location.totalWoMaintenanceWindow:filter(and(or(in(\"dt.entity.http_check\",entitySelector(\"type(http_check),not(tag(~\"AVAIL_RATE:FALSE~\"))\"))),or(in(\"dt.entity.http_check\",entitySelector(\"type(http_check),tag(~\"CI_ID_APP~\")\"))))):splitBy(\"dt.entity.http_check\"):sort(value(min,ascending))):names:fold(avg)&from=-"+str(l_timerange)+"m&to=now"
    
    return base_url

def avail_data_synthetic(l_timerange):
    
    base_url=DYNATRACE_URL+"/api/v2/metrics/query?metricSelector=(builtin:synthetic.browser.availability.location.totalWoMaintenanceWindow:filter(and(or(in(\"dt.entity.synthetic_test\",entitySelector(\"type(synthetic_test),not(tag(~\"AVAIL_RATE:FALSE~\"))\"))))):splitBy(\"dt.entity.synthetic_test\"):sort(value(min,ascending))):names:fold(avg)&from=-"+str(l_timerange)+"m&to=now"
    return base_url

def list_major_incident():
    oneinc=""
    url = SERVICENOW_URL+"/api/now/table/incident"
    params= {
        'sysparm_query': 'u_critical_incident_status=2^active=true',
    }
    user = config['SERVICENOW']['API_USER']
    password = config['SERVICENOW']['API_PASSWD']
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    datafile=BASE_DATA_DIR+'servicenow_list_major_inc.json'
    try:
        if REUSE and os.path.isfile(datafile) :
            with open(datafile) as f:
                json_data=json.load(f)
        else:
            logging.info("Query ServiceNow: find major inc, using URL["+url+"]")
            response = requests.get(url, auth=(user, password), headers=headers, params=params)
            response.raise_for_status()
            logging.debug("ServiceNow Query API response: "+str(response.status_code))
            json_data = response.json()
            logging.debug(json_data)
            with open(datafile, 'w', encoding='utf-8') as f:
                json.dump(json_data, f, ensure_ascii=False, indent=4)
            o_majorinc="BAD"
        if "result" in json_data:
            o_majorinc=json_data['result']      

    except Exception as err:
        logging.error(err)
        logging.error(traceback.format_exc())
    return o_majorinc
    
def list_ecr():
    oneinc=""
    url = SERVICENOW_URL+"/api/now/table/change_request"
    params= {
        'sysparm_query': 'active=true^type=emergency^state!=6^ORstate=NULL',
    #    'sysparm_fields': 'number,short_description,opened_at,u_resolved'
    }
    user = config['SERVICENOW']['API_USER']
    password = config['SERVICENOW']['API_PASSWD']
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    datafile=BASE_DATA_DIR+'servicenow_list_ecr.json'
    try:
        if REUSE and os.path.isfile(datafile) :
            with open(datafile) as f:
                json_data=json.load(f)
        else:
            logging.info("Query ServiceNow: find ecr, using URL["+url+"]")
            response = requests.get(url, auth=(user, password), headers=headers, params=params)
            response.raise_for_status()
            logging.debug("ServiceNow Query API response: "+str(response.status_code))
            json_data = response.json()
            logging.debug(json_data)
            with open(datafile, 'w', encoding='utf-8') as f:
                json.dump(json_data, f, ensure_ascii=False, indent=4)
            o_ecr=""
        if "result" in json_data:
            o_ecr=json_data['result']      

    except Exception as err:
        logging.error(err)
        logging.error(traceback.format_exc())
    return o_ecr    
    
logging.info("Start")
logging.info("Retrieve dynatrace_data data")
logging.debug("Debug mode enabled")
d_avail= avail_request(avail_data_http(timerange))
d_avail.extend(avail_request(avail_data_synthetic(timerange)))
#current status_code
d_availn= avail_request(avail_data_http(5))
d_availn.extend(avail_request(avail_data_synthetic(5)))
logging.debug("Avail Data lines: "+ str(len(d_avail)))
logging.debug(d_avail)
l_avail=[]
logging.info("Cleaning data")
for l in range(len(d_avail)):
    if 'HTTP' in d_avail[l]['dimensions'][1]:
        l_type='HTTP_CHECK'
    else:
        l_type='SYNTHETIC'
    if d_avail[l]['values'][0]<100:
        l_avail.append([l_type,d_avail[l]['dimensions'][0],round(d_avail[l]['values'][0],2),"UP"])
if len(l_avail)==0:
    l_avail.append(["All","All","No downtime during considered timeframe"])    

#find apps still DOWN
logging.info("Add current state")
for n in range(len(d_availn)):
    if d_availn[n]['values'][0]<100:
        checkn=d_availn[n]['dimensions'][0]
        for l in range(len(l_avail)):
            check=l_avail[l][1]
            logging.info(str(n)+"/"+str(l)+":"+checkn+"/"+check)
            if check == checkn:
                l_avail[l][3]="DOWN"                

env = Environment(loader=FileSystemLoader('.'))
template = env.get_template('template.html')

l_avail.sort(key = lambda x: x[2])

if not OA:
    logging.info("Gather SN data")
    l_major=list_major_incident()
    l_ecr=list_ecr()
else:
    l_major=[]
    l_ecr=[]

logging.info("Render data")
# Define column names
column_names = ['Type', 'Dimension', 'Value','Current state']
# Convert list to DataFrame with specified column names
df2 = pd.DataFrame(l_avail, columns=column_names)
mi_column_names = ['number', 'short_description']
ecr_column_names = ['number', 'reason', 'short_description']
df_mi = pd.DataFrame(l_major,columns=mi_column_names)
df_ecr = pd.DataFrame(l_ecr,columns=ecr_column_names)
note="Worst availability on last "+str(timerange)+" minutes (not shown if 100%)"
# Get the current date and time
current_datetime = datetime.now()  

formatted_current_datetime = current_datetime.strftime('%Y-%m-%d %H:%M:%S') 

# Render template with DataFrame, indices, and current date and time
rendered_table2 = template.render(table=df2, indices=df2.index, note=note, current_datetime=formatted_current_datetime,table_mi=df_mi, table_ecr=df_ecr)  

# Save rendered table as HTML file
html_file_path = BASE_DIR + "www" + os.sep + "AvailabilityDashboard.html"
with open(html_file_path, "w") as fh:   
    fh.write(rendered_table2)
logging.info("End")

