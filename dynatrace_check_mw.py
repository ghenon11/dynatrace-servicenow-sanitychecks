
#
# Made by Guillaume HENON
# November 2023
#
#
# Dynatrace test script of dt API used as a templte
# 
import logging,traceback,argparse,configparser
from logging import raiseExceptions
import os,datetime
import requests
import json
import time
from datetime import datetime
import pathlib
from utils import dynatrace_utils
    
from dynatrace import Dynatrace
from dynatrace.configuration_v1.maintenance_windows import (
    MaintenanceWindowService,
    TagCombination,
    MonitoredEntityFilter,
    Scope,
    Recurrence,
    Schedule,
    MaintenanceWindow,
    MaintenanceWindowStub,
)
from dynatrace.environment_v2.custom_tags import METag, TagContext
from dynatrace.pagination import PaginatedList
from dynatrace.environment_v2.monitored_entities import EntityShortRepresentation

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)) + os.sep)
BASE_DATA_DIR = BASE_DIR + 'data'+ os.sep
REUSE=False

ap = argparse.ArgumentParser(description="Script to compare open problems in Dynatrace and incidents in ServiceNow through API calls")
# Add the arguments to the parser
ap.add_argument("-d", "--debug", action="store_true",help="Set debug mode")
args = ap.parse_args()

isdebug=args.debug

# C:\Users\10023266\OneDrive - bioMerieux\ISOPS Core\dynatrace\Monaco\dynatrace-monaco\project_production

loglevel=logging.INFO
if isdebug:
    loglevel=logging.DEBUG

try:
    logname,ext=os.path.splitext(BASE_DIR+os.path.basename(__file__))
    logname=logname+".log"
    logging.basicConfig(format='%(asctime)s::%(levelname)s::%(message)s', filename=logname, filemode="w", level=loglevel)
except:
    logging.error("error when defining logging")

logging.info("START")    
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
TOKEN=config['DYNATRACE']['TOKEN_READ_AUDITLOGS']




def list_mw(dt: Dynatrace):
    mw = dt.maintenance_windows.list()
    assert isinstance(mw, PaginatedList)

    list_mw = list(mw)

    
    return list_mw

def mw_info(dt: Dynatrace,v_mw_id):
    mw = dt.maintenance_windows.get(mw_id=v_mw_id)

    return mw 

try:
    dt = Dynatrace(DYNATRACE_URL,TOKEN)

    logging.info("Loading MW")
    mw_list=[]
    mw_list=list_mw(dt);
    logging.debug(mw_list)

    mw_full={}
    logging.info("Loading MW details")
    for i in range(len(mw_list)):
    #for i in range(2):
        mw_id=mw_list[i].id
        logging.info("Looking MW id: "+mw_id)
        mw_full=mw_info(dt,mw_id)
        logging.debug(mw_full)
        entities=mw_full.scope.entities
        matches=mw_full.scope.matches
        
        metric_value=1
        if not entities and not matches:
            logging.warning("MaintenanceWindow ID["+mw_full.id+"] name["+mw_full.name+"] has no defined scope")
            metric_value=0 #unhealthy state
            break
        else:
            logging.info("MW scope is defined: Entities:"+str(entities)+" Matches:"+str(matches))

    logging.info("Final status (1=healthy): "+str(metric_value))
 
    dynatrace_utils.send_metric("apps.web.dynatrace.mw_scope.nofilter",metric_value)
    
except Exception as err:
        logging.error(err)
        logging.error(traceback.format_exc())
        exit()
        
logging.info("END")