#
# Made by Guillaume HENON
# October 2023
#
import logging,traceback,argparse, configparser
import jinja2
from logging import raiseExceptions
import os,datetime
import requests
import json
import re
from datetime import datetime

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)) + os.sep)
BASE_DATA_DIR = BASE_DIR + 'data'+ os.sep
REUSE=False

ap = argparse.ArgumentParser(description="Script to compare open problems in Dynatrace and incidents in ServiceNow through API calls")
# Add the arguments to the parser
ap.add_argument("-d", "--debug", action="store_true",help="Set debug mode")
args = ap.parse_args()

isdebug=args.debug
loglevel=logging.INFO
if isdebug:
    loglevel=logging.DEBUG

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

# https://stackoverflow.com/questions/52559412/search-nested-json-dict-for-multiple-key-values-matching-specified-keys


def build_open_problems():
    problemList=[]
    
    smatch=[]
    for i in config['DYNATRACE']['ALERTING_PROFILE_TO_CONSIDER'].split(','): 
        smatch.append(i)
    logging.debug(smatch)
    
    base_url=DYNATRACE_URL+"/api/v2/problems?pageSize=200&sort=startTime&problemSelector=status(open)"
    datafile=BASE_DATA_DIR+'dynatrace_data.json'
    token=config['DYNATRACE']['TOKEN_READ_PROBLEMS']
    session = requests.Session()
    session.headers.update({"Accept":"application/json"})
    session.headers.update({"Content-Type":"application/json"})
    session.headers.update({"Authorization": "Api-Token "+token})
    try:
        if REUSE and os.path.isfile(datafile) :
            with open(datafile) as f:
                json_data=json.load(f)
        else:
            response = session.get(base_url)
            response.raise_for_status()
            logging.debug("Problem API response: "+str(response.status_code))
       #     text = json.dumps(response.json(), sort_keys=True, indent=4)
            json_data = response.json()
            with open(BASE_DATA_DIR+'dynatrace_data.json', 'w', encoding='utf-8') as f:
                json.dump(json_data, f, ensure_ascii=False, indent=4)

        openproblemscount=json_data['totalCount']
        logging.info("Open Problems:"+str(openproblemscount))
        openproblems=json_data['problems']
        logging.debug(type(openproblems))
        for i in range(len(openproblems)):
        #     problemId =json_data['problems'][i]['displayId']
        #     problemTitle=json_data['problems'][i]['title']
            #https://uko53003.live.dynatrace.com/#problems/problemdetails;gtf=-2h;gf=all;pid=1013777397501840009_1697191620000V2
            openproblems[i]['ProblemUrl']=DYNATRACE_URL+"/#problems/problemdetails;gtf=-2h;gf=all;pid="+openproblems[i]['problemId']
            problemStartime_ts=openproblems[i]['startTime']
            problemStartime=datetime.fromtimestamp(int(problemStartime_ts)/1000).strftime("%Y-%m-%d %H:%M:%S")
            openproblems[i]['datetime_startTime']=problemStartime
            problemAlerting=openproblems[i]['problemFilters']
            problemaffectedEntities=openproblems[i]['affectedEntities']
            mainEntity=problemaffectedEntities[0]['name']
            openproblems[i]['main_affectedEntity']=mainEntity
            logging.debug(str(i)+" | "+openproblems[i]['displayId']+" | "+openproblems[i]['title']+" | "+ openproblems[i]['datetime_startTime']+" | "+openproblems[i]['main_affectedEntity'])
            #smatch=["ServiceNow", "HealthCheck", "Synthetic"]
            openproblems[i]['Expected_ServiceNow']=False
            SNIncidenttag=True
            for a in problemAlerting:
                if any(any(x in y for y in a.values() if y is not None) for x in smatch): #{k: v for k, v in original.items() if v is not None}
                    openproblems[i]['Expected_ServiceNow']=True
            for b in openproblems[i]['entityTags']:
                if "SN_INCIDENT:False" in b.values():
                    SNIncidenttag=False
            if openproblems[i]['Expected_ServiceNow']==True and SNIncidenttag==False:
                openproblems[i]['Expected_ServiceNow']=False

                    
    except requests.exceptions.HTTPError as errh:
        logging.error(errh)
    except requests.exceptions.ConnectionError as errc:
        logging.error(errc)
    except requests.exceptions.Timeout as errt:
        logging.error(errt)
    except requests.exceptions.RequestException as err:
        logging.error(err)
    return openproblems


def find_incident_from_problem(PrbID):
    oneinc=""
    url = SERVICENOW_URL+"/api/now/table/incident?sysparm_query=short_descriptionCONTAINS"+PrbID+"%3A^sys_created_by=dynatrace_user&sysparm_view=Desktop&sysparm_display_value=true"
# we look at last run to see if we already have the sys_id as query with sys_id is quickest   
    result_datafile=BASE_DATA_DIR+'result.json'
    if os.path.isfile(result_datafile):
        with open(result_datafile) as rf:
            sanity_data=json.load(rf)
        for l in range(len(sanity_data)):
            if PrbID in sanity_data[l].values():
                if "Incident" in sanity_data[l]:
                    if "sys_id" in sanity_data[l]['Incident']:
                        IncidentSys_id=sanity_data[l]['Incident']['sys_id']
                        url = SERVICENOW_URL+"/api/now/table/incident?sysparm_query=sys_id%3D"+IncidentSys_id+"&sysparm_view=Desktop&sysparm_display_value=true"

    # Set the request parameters
    # https://developer.servicenow.com/dev.do#!/reference/api/vancouver/rest/c_TableAPI
    # %3A is : encoded https://www.urlencoder.io/learn/
    #url = SERVICENOW_URL+"/api/now/table/incident?sysparm_query=short_descriptionCONTAINS"+PrbID+"%3A^sys_created_by=dynatrace_user&sysparm_view=Desktop&sysparm_display_value=true"
    user = config['SERVICENOW']['API_USER']
    password = config['SERVICENOW']['API_PASSWD']
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    datafile=BASE_DATA_DIR+'servicenow_prb_'+PrbID+'.json'
    try:
        if REUSE and os.path.isfile(datafile) :
            with open(datafile) as f:
                json_data=json.load(f)
        else:
            logging.info("Query ServiceNow: find incident for problem ["+PrbID+"], using URL["+url+"]")
            response = requests.get(url, auth=(user, password), headers=headers)
            response.raise_for_status()
            logging.debug("DynatraceProblem ["+PrbID+"] API response: "+str(response.status_code))
            #text = json.dumps(response.json(), sort_keys=True, indent=4)
            #logging.info("tt"+text)
            json_data = response.json()
            with open(BASE_DATA_DIR+'servicenow_prb_'+PrbID+'.json', 'w', encoding='utf-8') as f:
                json.dump(json_data, f, ensure_ascii=False, indent=4)
        if "result" in json_data:
            oneinc=json_data['result']
        else:
            oneinc=""

    except requests.exceptions.HTTPError as errh:
        logging.error(errh)
    except requests.exceptions.ConnectionError as errc:
        logging.error(errc)
    except requests.exceptions.Timeout as errt:
        logging.error(errt)
    except requests.exceptions.RequestException as err:
        logging.error(err)
        print(traceback.format_exc())
    return oneinc


logging.info("Start")
logging.info("Retrieve Problems")

d_openPrb=build_open_problems()
logging.debug("Problems expected in ServiceNow: "+ str(len(d_openPrb)))
logging.debug(d_openPrb)

# for each problem find incident information in ServiceNow and add the information to the problem dictionary
nberror=0
nbwarning=0
nbana=0
l_sum=[]
len_openPrb=len(d_openPrb)
for l in range(len_openPrb):
    logging.debug("record["+str(l)+"] ProblemID="+d_openPrb[l]['displayId']+" Expected["+str(d_openPrb[l]['Expected_ServiceNow'])+"]")
    oneprb=d_openPrb[l]['displayId']
    if d_openPrb[l]['Expected_ServiceNow']:
        logging.info('Retrieve incident info for Problem ['+oneprb+'] Progress['+str(l+1)+"/"+str(len_openPrb)+"]")
        nbana+=1
        d_oneinc=find_incident_from_problem(oneprb)
        if not d_oneinc:
            logging.error('No incident for problem '+oneprb+' !!!')
            statusana="No Incident for problem"
            statusanacode='ERROR'
            nberror+=1
        else:
            logging.debug(type(d_oneinc))
            logging.debug('incident['+d_oneinc[0]['number']+'] State['+d_oneinc[0]['state']+']  Title['+d_oneinc[0]['short_description']+']')
            logging.debug(d_oneinc[0]['description'])
            # Add all incident information to the dictionary of current problem
            d_openPrb[l]['Incident']=d_oneinc[0]
            d_openPrb[l]['Incident']['IncidentUrl']=SERVICENOW_URL+"/nav_to.do?uri=%2Fincident.do%3Fsys_id%3D"+d_openPrb[l]['Incident']['sys_id']
            IncState=d_openPrb[l]['Incident']['state']
            IncNumber=d_openPrb[l]['Incident']['number']
            logging.info("ProblemId["+d_openPrb[l]['displayId']+"] IncidentId["+d_openPrb[l]['Incident']['number']+"] Opened["+d_openPrb[l]['datetime_startTime']+"] State["+IncState+"] Title["+d_openPrb[l]['Incident']['short_description']+"] Entity["+d_openPrb[l]['main_affectedEntity']+"]")
            statusana="Incident in progress"
            statusanacode='OK'
            if IncState in ['Resolved','Closed']:
                logging.warning("Incident["+IncNumber+"] is resolved while problem is still open !")
                statusana="Incident resolved while problem is still open"
                statusanacode='WARNING'
                nbwarning+=1
    else:
        logging.info('No Incident expected for Problem '+oneprb+' Progress['+str(l+1)+"/"+str(len_openPrb)+"]")
        statusana="No Incident expected"
        statusanacode='NO_INC'
    d_openPrb[l]['SanityStatus']=statusana
    d_openPrb[l]['SanityStatusCode']=statusanacode

#save result
with open(BASE_DATA_DIR+'result.json', 'w') as fp:
    json.dump(d_openPrb, fp)
    
logging.info("-->SUMMARY: ERROR["+str(nberror)+"] WARNING["+str(nbwarning)+"] ANALYZED["+str(nbana)+"] TOTAL["+str(len_openPrb)+"]")

logging.info("Create Web page")
#build list with needed information
l_webpage=[]
l_webpage.append(["#","ProblemNumber","Created","Summary","Entity","IncidentNumber","IncidentState","Sanity Status","Comments"])
for l in range(len_openPrb):
    logging.debug(str(l)+" "+str(d_openPrb[l]['SanityStatusCode']))
    if str(d_openPrb[l]['SanityStatusCode']) in ["ERROR","NO_INC"]:
        l_webpage.append([str(l),"<a href="+d_openPrb[l]['ProblemUrl']+" target=\"_blank\" rel=\"noopener noreferrer\">"+d_openPrb[l]['displayId']+"</a>",d_openPrb[l]['datetime_startTime'],d_openPrb[l]['title'],d_openPrb[l]['main_affectedEntity'],"","",d_openPrb[l]['SanityStatusCode'],d_openPrb[l]['SanityStatus']])
    else:
        l_webpage.append([str(l),"<a href="+d_openPrb[l]['ProblemUrl']+" target=\"_blank\" rel=\"noopener noreferrer\">"+d_openPrb[l]['displayId']+"</a>",d_openPrb[l]['datetime_startTime'],d_openPrb[l]['title'],d_openPrb[l]['main_affectedEntity'],"<a href="+d_openPrb[l]['Incident']['IncidentUrl']+" target=\"_blank\" rel=\"noopener noreferrer\">"+d_openPrb[l]['Incident']['number']+"</a>",d_openPrb[l]['Incident']['state'],d_openPrb[l]['SanityStatusCode'],d_openPrb[l]['SanityStatus']])
logging.debug(l_webpage)


template= jinja2.Template("""
<html>
<title>Dynatrace - ServiceNow sanity check</title>
<style type="text/css">
    table,th,td {
        border-collapse: collapse;
        border: 1px solid #8E8F3A
    }
    .red {
        color: red;
    }
    .yellow {
        color: yellow;
    }
    .green {
        color: green;
    }
</style>
<h1 align=center><b>Dynatrace - ServiceNow Sanity Check</b></h1>
<h2 align=center>Status of Incidents linked to Open Problems</h1>
<p>Last Update at {{ now() }}</p>
<table>
{% for row in attrs %}
<tr>
    {% if loop.index == 1 %}
        {% for cell in row %}
            <th>{{cell}}</th>
        {% endfor %}
    {% else %}
        {% for cell in row %}
            <td class="{{'red' if cell == "ERROR"}}">{{cell}}</td>
        {% endfor %}
    {% endif %}
</tr>
{% endfor %}
</table>
""")

template.globals['now'] = datetime.now
output_from_parsed_template=template.render({'attrs': l_webpage})
with open(BASE_DIR+"www"+os.sep+ "SanityCheck.html", "w") as fh:
    fh.write(output_from_parsed_template)

logging.info("End")
