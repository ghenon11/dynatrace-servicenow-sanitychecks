# dynatracae_utils.py>
#
# Made by Guillaume HENON
# November 2023
#
#
# Dynatrace utils
# 

import logging,traceback,configparser
import os,datetime
import requests
import time
from datetime import datetime
import pathlib

def send_metric(v_metric,v_value):
    # Custom metric data (replace placeholders with actual values)
    #nowtimestamp=int(datetime.timestamp(datetime.now()) * 1000)
    try:
        logging.getLogger()
        metric_configfile="dynatrace_sanity_checks.ini"
        if os.path.isfile(metric_configfile):
            metric_config = configparser.ConfigParser()
            metric_config.read(metric_configfile)
        else:
            logging.error("Config file ["+metric_configfile+"] is missing")
            return 0
        
        api_token=metric_config['DYNATRACE']['TOKEN_METRICS'] 
        DYNATRACE_URL=metric_config['DYNATRACE']['URL']          
        dynatrace_api_url=DYNATRACE_URL+"/api/v2/metrics/ingest"
        headers = {"Authorization": "Api-Token " + api_token, "Content-Type": "text/plain"}
        data=v_metric+",dt.entity.application=APPLICATION-3A1C3B782A04AC39 "+str(v_value)
        logging.debug(data)
        response = requests.post(dynatrace_api_url, headers=headers, data=data)

    # Check the response status

        logging.info(str(response))
        # Check the response status
        if response.status_code == 202:
            logging.info("Metrics sent successfully")
        else:
            logging.error("Failed to send metrics. Status code:"+str(response.status_code)+", Response: "+response.text)
        
    except Exception as err:
        logging.error(err)
        logging.error(traceback.format_exc())
        return 0

    return response.status_code   
