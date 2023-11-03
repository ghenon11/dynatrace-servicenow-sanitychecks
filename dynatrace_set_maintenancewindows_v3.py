#
# Script to create maintenance windows in Dynatrace through an API call
#
# Create in dynatrace a maintenance windows starting immediately for one hour on all hosts which have their name containing one of the strings passed as argument
# Example: python.exe dynatrace_set_maintenancewindows_v3.py frox1,frox02
#
# Guillaume HENON - October 2023
#
import logging,traceback,argparse, configparser
from logging import raiseExceptions
import os,math,glob
from datetime import datetime, timedelta, timezone
import requests
import json

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)) + os.sep)
BASE_DATA_DIR = BASE_DIR + 'data'+ os.sep
#DYNATRACE_URL="https://uko53003.live.dynatrace.com"
#DYNATRACE_URL="https://prn04249.live.dynatrace.com"


ap = argparse.ArgumentParser(description="Script to create maintenance windows in Dynatrace through an API call")
# Add the arguments to the parser
ap.add_argument("EntitiesSearchString", type=str,help="Strings to match Entities that will be included in Maintenance-Window (comma separated). ")
ap.add_argument("-t", "--test", action="store_true",help="Test Run: If set, final API call to create maintenance window is not done")
ap.add_argument("-d", "--debug", action="store_true",help="Set debug mode")
args = ap.parse_args()

v_entitysearch=args.EntitiesSearchString
istest=args.test

isdebug=args.debug
loglevel=logging.INFO
if isdebug:
    loglevel=logging.DEBUG
    
logname,ext=os.path.splitext(BASE_DIR+os.path.basename(__file__))
logname=logname+".log"
logging.basicConfig(format='%(asctime)s::%(levelname)s::%(message)s', filename=logname,filemode='w',level=loglevel)

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
ACCESS_TOKEN=config['DYNATRACE']['TOKEN_WRITE_SETTINGS']

def cleanup():
    try:
        for filename in glob.glob(BASE_DATA_DIR+"dynatrace_find_entityid_*"):
            logging.info('Removing '+filename)
            os.remove(filename) 
    except Exception as err:
        logging.error(err)
        print(traceback.format_exc())
        
def find_entityid(i_entityname):
    #base_url=DYNATRACE_URL+"/api/v2/entities?entitySelector=type%28%22HOST%22%29%2CentityName.equals%28%22"+i_entityname+"%22%29"    
    base_url=DYNATRACE_URL+"/api/v2/entities?entitySelector=type%28%22HOST%22%29%2CentityName%28%22"+i_entityname+"%22%29"    
    datafile=BASE_DATA_DIR+"dynatrace_find_entityid_"+i_entityname+".json"
    logging.info('Retrieve Entities matching['+i_entityname+']')
    session = requests.Session()
    token=config['DYNATRACE']['TOKEN_READ_ENTITY']
    session.headers.update({"Accept":"application/json"})
    session.headers.update({"Content-Type":"application/json"})
    session.headers.update({"Authorization": "Api-Token "+token})
    try:
        response = session.get(base_url)
        response.raise_for_status()
        logging.debug("Auditlogs API response: "+str(response.status_code))
        o_entity = response.json()
        with open(datafile, 'w', encoding='utf-8') as f:
            json.dump(o_entity, f, ensure_ascii=False, indent=4)
                    
    except Exception as err:
        logging.error(err)
        print(traceback.format_exc())
    return o_entity
    
def set_maintenance_windows(l_dicttopost):
    base_url=DYNATRACE_URL+"/api/v2/settings/objects?schemaIds=builtin%3Aalerting.maintenance-window"  
    token=config['DYNATRACE']['TOKEN_WRITE_SETTINGS']    
    session = requests.Session()
    session.headers.update({"Accept":"application/json"})
    session.headers.update({"Content-Type":"application/json"})
    session.headers.update({"Authorization": "Api-Token "+token})
    try:
        response = session.post(base_url, json=l_dicttopost)
       # response.raise_for_status()
        logging.debug("Set Maintenance-Window API response: "+str(response.status_code))
        o_mw = response.json()
        logging.info(o_mw)
        response.raise_for_status()
    except Exception as err:
        logging.error(err)
        print(traceback.format_exc())
    return o_mw

def build_mw_json(i_entity):
    # reading the template
    js = [ { 'schemaId':'builtin:alerting.maintenance-window', 'schemaVersion':'2.14.4', 'scope':'environment', 'value': {  'enabled': True, 'generalProperties': { 'name': 'OneHostMaintenanceWindows_<HOSTNAME>', 'maintenanceType': 'PLANNED', 'suppression': 'DETECT_PROBLEMS_DONT_ALERT', 'disableSyntheticMonitorExecution': False }, 'schedule': { 'scheduleType': 'ONCE', 'onceRecurrence': { 'startTime':'<DATE DEBUT>', 'endTime': '<DATE_FIN>', 'timeZone': 'UTC' } }, 'filters': [ { 'entityType': 'HOST', 'entityId': '<HOST_ID>', 'entityTags': [], 'managementZones': [] } ] } }]
    #set date, format 2023-10-24T18:20:00, from now+2mins for 1hour"
    v_starttime=datetime.now(timezone.utc)+timedelta(minutes=2)
    v_endtime=v_starttime + timedelta(hours=1)
    logging.debug("Start["+str(v_starttime)+"] End["+str(v_endtime)+"]")
    js[0]['value']['schedule']['onceRecurrence']['startTime']=v_starttime.strftime("%Y-%m-%dT%H:%M:%S")
    js[0]['value']['schedule']['onceRecurrence']['endTime']=v_endtime.strftime("%Y-%m-%dT%H:%M:%S")
    js[0]['value']['generalProperties']['name']="Automated 1 Hour Maintenance Window starting "+v_starttime.strftime("%Y-%m-%dT%H:%M:%S") +" UTC on "+str(len(i_entity['entities']))+" entities, names containing "+i_entity['SearchEntities']
    logging.info("Build Body for: "+js[0]['value']['generalProperties']['name'])
    #if more than one entityId
    for i in range(len(i_entity['entities'])-1):
        js[0]['value']['filters'].append({'entityType': 'HOST', 'entityId': '<HOST_ID>', 'entityTags': [],'managementZones': []})
    for i in range(len(i_entity['entities'])):
        js[0]['value']['filters'][i]['entityId']=i_entity['entities'][i]['entityId']
    return js

logging.info("Start")
logging.info("Retrieve Entities")

try:
    v_entitynames = v_entitysearch.split(",")    
    v_entity={}
    for i in range(len(v_entitynames)):
        v_tempentity=find_entityid(v_entitynames[i])
        if i==0:
            v_entity=v_tempentity
        else:
            for j in range(len(v_tempentity['entities'])):
                v_entity['entities'].append(v_tempentity['entities'][j])
    v_entity['SearchEntities']=v_entitysearch
    logging.info(v_entity)
    if v_entity['entities']: 
        v_entityid=v_entity['entities'][0]['entityId']
        logging.info("First EntityId["+v_entityid+"] EntityName["+v_entity['entities'][0]['displayName']+"]")
        logging.info("Build JSON body for API")
        v_jsontopost=build_mw_json(v_entity)
        logging.info(v_jsontopost)
        logging.info("Call API to set maintenance window")
        if not istest:
            v_mv=set_maintenance_windows(v_jsontopost)
            if v_mv[0]['objectId']:
                logging.info("Maintenance window set")
            else:
                logging.error("MV creation failed")
        else:
            logging.info("Test Run")
    else:
        logging.warning("No entityId found for "+str(v_entitynames))
    
    logging.info("Cleanup")
    cleanup()

except Exception as err:
        logging.error(err)
        print(traceback.format_exc())    

logging.info("End")