#!/usr/bin/python

import hashlib
from optparse import OptionParser
import os
import time
import logging
import sys
import json
import csv
import math
import socket
import subprocess
from ConfigParser import SafeConfigParser
import validators

'''
This script reads reporting_config.json and .agent.bashrc
and opens daily metric file and reports header + rows within
window of reporting interval after prev endtime
if prev endtime is 0, report most recent reporting interval
till now from today's metric file (may or may not be present)
assumping gmt epoch timestamp and local date daily file. 

This also allows you to replay old log and metric files 
'''


def get_parameters():
    usage = "Usage: %prog [options]"
    parser = OptionParser(usage=usage)
    parser.add_option("-f", "--fileInput",
                      action="store", dest="inputFile", help="Input data file (overriding daily data file)")
    parser.add_option("-r", "--logFolder",
                      action="store", dest="logFolder", help="Folder to read log files from")
    parser.add_option("-m", "--mode",
                      action="store", dest="mode", help="Running mode: live or metricFileReplay or logFileReplay")
    parser.add_option("-d", "--directory",
                      action="store", dest="homepath", help="Directory to run from")
    parser.add_option("-t", "--agentType",
                      action="store", dest="agentType", help="Agent type")
    parser.add_option("-w", "--serverUrl",
                      action="store", dest="serverUrl", help="Server Url")
    parser.add_option("-s", "--splitID",
                      action="store", dest="splitID", help="The split ID to use when grouping results on the server")
    parser.add_option("-g", "--splitBy",
                      action="store", dest="splitBy",
                      help="The 'split by' to use when grouping results on the server. Examples: splitByEnv, splitByGroup")
    parser.add_option("-z", "--timeZone",
                      action="store", dest="timeZone", help="Time Zone")
    parser.add_option("-c", "--chunkSize",
                      action="store", dest="chunkSize", help="Max chunk size in KB")
    parser.add_option("-l", "--chunkLines",
                      action="store", dest="chunkLines", help="Max number of lines in chunk")
    parser.add_option("-l", "--log_level",
                      action="store", dest="log_level", help="Change log verbosity(WARNING: 0, INFO: 1, DEBUG: 2)")

    (options, args) = parser.parse_args()

    params = {}

    params['homepath'] = os.getcwd() if not options.homepath else options.homepath
    params['mode'] = "live" if not options.mode else options.mode
    params['agentType'] = "" if not options.agentType else options.agentType
    params['serverUrl'] = 'https://app.insightfinder.com' if not options.serverUrl else options.serverUrl
    params['inputFile'] = None if not options.inputFile else options.inputFile
    params['logFolder'] = None if not options.logFolder else options.logFolder
    params['timeZone'] = "GMT" if not options.timeZone else options.timeZone
    params['splitID'] = None if not options.splitID else options.splitID
    params['chunkLines'] = None if not options.splitBy else options.splitBy

    if options.chunkLines is None and params['agentType'] == 'metricFileReplay':
        params['chunkLines'] = 100
    elif options.chunkLines is None:
        params['chunkLines'] = 40000
    else:
        params['chunkLines'] = int(options.chunkLines)

    params['log_level'] = logging.INFO
    if options.log_level == '0':
        params['log_level'] = logging.WARNING
    elif options.log_level == '1':
        params['log_level'] = logging.INFO
    elif options.log_level >= '2':
        params['log_level'] = logging.DEBUG
    return params


def get_agent_config_vars():
    config_vars = {}
    try:
        if os.path.exists(os.path.join(parameters['homepath'], "common", "config.ini")):
            parser = SafeConfigParser()
            parser.read(os.path.join(parameters['homepath'], "common", "config.ini"))
            insightfinder_license_key = parser.get('insightfinder', 'insightfinder_license_key')
            insightfinder_project_name = parser.get('insightfinder', 'insightfinder_project_name')
            insightfinder_user_name = parser.get('insightfinder', 'insightfinder_user_name')
            sampling_interval = parser.get('insightfinder', 'sampling_interval')

            if not (len(insightfinder_license_key) and len(insightfinder_project_name) and len(
                    insightfinder_user_name) and len(sampling_interval)):
                logger.error("Agent not correctly configured. Check config file.")
                sys.exit(1)

            config_vars['license_key'] = insightfinder_license_key
            config_vars['project_name'] = insightfinder_project_name
            config_vars['user_name'] = insightfinder_user_name
            config_vars['sampling_interval'] = sampling_interval
    except IOError:
        logger.error("config.ini file is missing")
    return config_vars


def get_reporting_config_vars():
    reporting_config_vars_l = {}
    with open(os.path.join(parameters['homepath'], "reporting_config.json"), 'r') as f:
        config = json.load(f)
    reporting_interval_string = config['reporting_interval']
    # is_second_reporting = False
    if reporting_interval_string[-1:] == 's':
        # is_second_reporting = True
        reporting_interval = float(config['reporting_interval'][:-1])
        reporting_config_vars_l['reporting_interval'] = float(reporting_interval / 60.0)
    else:
        reporting_config_vars_l['reporting_interval'] = int(config['reporting_interval'])
        reporting_config_vars_l['keep_file_days'] = int(config['keep_file_days'])
        reporting_config_vars_l['prev_endtime'] = config['prev_endtime']
        reporting_config_vars_l['deltaFields'] = config['delta_fields']
    return reporting_config_vars_l


def update_data_start_time():
    if "FileReplay" in parameters['mode'] and reporting_config_vars['prev_endtime'] != "0" and len(
            reporting_config_vars['prev_endtime']) >= 8:
        start_time = reporting_config_vars['prev_endtime']
        # pad a second after prev_endtime
        start_time_epoch = 1000 + long(1000 * time.mktime(time.strptime(start_time, "%Y%m%d%H%M%S")))
        # end_time_epoch = start_time_epoch + 1000 * 60 * reporting_config_vars['reporting_interval']
    elif reporting_config_vars['prev_endtime'] != "0":
        start_time = reporting_config_vars['prev_endtime']
        # pad a second after prev_endtime
        start_time_epoch = 1000 + long(1000 * time.mktime(time.strptime(start_time, "%Y%m%d%H%M%S")))
        # end_time_epoch = start_time_epoch + 1000 * 60 * reporting_config_vars['reporting_interval']
    else:  # prev_endtime == 0
        end_time_epoch = int(time.time()) * 1000
        start_time_epoch = end_time_epoch - 1000 * 60 * reporting_config_vars['reporting_interval']
    return start_time_epoch


# update prev_endtime in config file
def update_timestamp(prev_endtime):
    with open(os.path.join(parameters['homepath'], "reporting_config.json"), 'r') as f:
        config = json.load(f)
    config['prev_endtime'] = prev_endtime
    with open(os.path.join(parameters['homepath'], "reporting_config.json"), "w") as f:
        json.dump(config, f)


def get_index_for_column_name(col_name):
    if col_name == "CPU":
        return 1
    elif col_name == "DiskRead" or col_name == "DiskWrite":
        return 2
    elif col_name == "DiskUsed":
        return 3
    elif col_name == "NetworkIn" or col_name == "NetworkOut":
        return 4
    elif col_name == "MemUsed":
        return 5


def get_ec2_instancetype():
    url = "http://169.254.169.254/latest/meta-data/instance-type"
    try:
        response = requests.post(url)
    except requests.ConnectionError:
        logger.error("Error finding instance-type")
        return
    if response.status_code != 200:
        logger.error("Error finding instance-type")
        return
    return response.text


def send_data(metric_data_dict, file_path, chunk_serial_number):
    send_data_time = time.time()
    to_send_data_dict = {}
    # prepare data for metric streaming agent
    to_send_data_json = fill_to_send_data_dict(chunk_serial_number, file_path, metric_data_dict, to_send_data_dict)
    # send the data
    send_data_to_backend(metric_data_dict, send_data_time, to_send_data_dict, to_send_data_json)
    logger.debug("--- Send data time: %s seconds ---" % (time.time() - send_data_time))
    return


def fill_to_send_data_dict(chunk_serial_number, file_path, metric_data_dict, to_send_data_dict):
    if parameters['mode'] == "metricFileReplay":
        to_send_data_dict["metricData"] = json.dumps(metric_data_dict[0])
    else:
        to_send_data_dict["metricData"] = json.dumps(metric_data_dict)
    to_send_data_dict["licenseKey"] = agent_config_vars['license_key']
    to_send_data_dict["projectName"] = agent_config_vars['project_name']
    to_send_data_dict["userName"] = agent_config_vars['user_name']
    to_send_data_dict["instanceName"] = socket.gethostname().partition(".")[0]
    to_send_data_dict["samplingInterval"] = str(int(reporting_config_vars['reporting_interval'] * 60))
    if parameters['agentType'] == "ec2monitoring":
        to_send_data_dict["instanceType"] = get_ec2_instancetype()
    # additional data to send for replay agents
    if "FileReplay" in parameters['mode']:
        to_send_data_dict["fileID"] = hashlib.md5(file_path).hexdigest()
        if parameters['mode'] == "logFileReplay":
            to_send_data_dict["agentType"] = "LogFileReplay"
            to_send_data_dict["minTimestamp"] = ""
            to_send_data_dict["maxTimestamp"] = ""
        if parameters['mode'] == "metricFileReplay":
            to_send_data_dict["agentType"] = "MetricFileReplay"
            to_send_data_dict["minTimestamp"] = str(metric_data_dict[1])
            to_send_data_dict["maxTimestamp"] = str(metric_data_dict[2])
            to_send_data_dict["chunkSerialNumber"] = str(chunk_serial_number)
        if 'splitID' in parameters.keys() and 'splitBy' in parameters.keys():
            to_send_data_dict["splitID"] = parameters['splitID']
            to_send_data_dict["splitBy"] = parameters['splitBy']
    to_send_data_json = json.dumps(to_send_data_dict)
    logger.debug("Chunksize: " + str(len(bytearray(str(metric_data_dict)))) + "\n" + "TotalData: " + str(
        len(bytearray(to_send_data_json))))
    return to_send_data_json


def send_data_to_backend(metric_data_dict, to_send_data_dict, to_send_data_json):
    post_url = parameters['serverUrl'] + "/customprojectrawdata"
    if parameters['agentType'] == "hypervisor":
        send_hypervisor_agent_details(metric_data_dict, post_url, to_send_data_dict, to_send_data_json)
    else:
        send_other_agent_details(metric_data_dict, post_url, to_send_data_dict, to_send_data_json)


def send_other_agent_details(metric_data_dict, post_url, to_send_data_dict, to_send_data_json):
    # response = requests.post(post_url, data=json.loads(to_send_data_json))
    if send_http_request(post_url, "post", json.loads(to_send_data_json)):
        logger.info(str(len(bytearray(to_send_data_json))) + " bytes of data are reported.")
    else:
        send_data_in_two_chunks(metric_data_dict, post_url, to_send_data_dict)


def send_data_in_two_chunks(metric_data_dict, post_url, to_send_data_dict):
    data_split1 = metric_data_dict[0:len(metric_data_dict) / 2]
    to_send_data_dict["metricData"] = json.dumps(data_split1)
    to_send_data_json = json.dumps(to_send_data_dict)
    if send_http_request(post_url, "post", json.loads(to_send_data_json),
                         str(len(bytearray(to_send_data_json))) + " bytes of data are reported.",
                         "Failed to send data."):
        parameters['chunkLines'] = parameters['chunkLines'] / 2
        # since succeeded send the rest of the chunk
        data_split2 = metric_data_dict[len(metric_data_dict) / 2:]
        to_send_data_dict["metricData"] = json.dumps(data_split2)
        to_send_data_json = json.dumps(to_send_data_dict)
        send_http_request(post_url, "post", json.loads(to_send_data_json))
    return


# retry once for failed data and set chunkLines to half if succeeded
def send_hypervisor_agent_details(metric_data_dict, post_url, to_send_data_dict, to_send_data_json):
    response = urllib.urlopen(post_url, data=urllib.urlencode(to_send_data_dict))
    if response.getcode() == 200:
        logger.info(str(len(bytearray(to_send_data_json))) + " bytes of data are reported.")
    else:
        # retry once for failed data and set chunkLines to half if succeeded
        logger.error("Failed to send data. Retrying once.")
        data_split1 = metric_data_dict[0:len(metric_data_dict) / 2]
        to_send_data_dict["metricData"] = json.dumps(data_split1)
        response = urllib.urlopen(post_url, data=urllib.urlencode(to_send_data_dict))
        if response.getcode() == 200:
            logger.info(str(len(bytearray(to_send_data_json))) + " bytes of data are reported.")
            parameters['chunkLines'] = parameters['chunkLines'] / 2
            # since succeeded send the rest of the chunk
            data_split2 = metric_data_dict[len(metric_data_dict) / 2:]
            to_send_data_dict["metricData"] = json.dumps(data_split2)
            response = urllib.urlopen(post_url, data=urllib.urlencode(to_send_data_dict))
        else:
            logger.info("Failed to send data.")


def send_http_request(url, type, data, succ_message="Request successful!", fail_message="Request Failed"):
    if validators.url(url):
        if type == "get":
            response = requests.get(url, data)
        else:
            response = requests.post(url, data)

        if response.status_code == 200:
            logger.info(succ_message)
            return True
        logger.info(fail_message)
        return False
    else:
        logger.info("Url not correct : " + url)
    return True


def process_streaming(new_prev_end_time_epoch):
    metric_data = []
    dates = []
    # get dates to read files for
    for i in range(0, 3 + int(float(reporting_config_vars['reporting_interval']) / 24 / 60)):
        dates.append(time.strftime("%Y%m%d", time.localtime(startTimeEpoch / 1000 + 60 * 60 * 24 * i)))
    # append current date to dates
    current_date = time.strftime("%Y%m%d", time.gmtime())
    if current_date not in dates:
        dates.append(current_date)

    new_prev_end_time_epoch = read_data_from_selected_files(dates, metric_data, new_prev_end_time_epoch)
    # update endtime in config
    if new_prev_end_time_epoch == 0:
        logger.info("No data is reported")
    else:
        new_prev_endtime_in_sec = math.ceil(long(new_prev_end_time_epoch) / 1000.0)
        new_prev_endtime = time.strftime("%Y%m%d%H%M%S", time.localtime(long(new_prev_endtime_in_sec)))
        update_timestamp(new_prev_endtime)
        send_data(metric_data, None, None)
    return


def read_data_from_selected_files(dates, metric_data, new_prev_end_time_epoch):
    # read all selected daily files for data
    for date in dates:
        filename_addition = ""
        if parameters['agentType'] == "kafka":
            filename_addition = "_kafka"
        elif parameters['agentType'] == "elasticsearch-storage":
            filename_addition = "_es"

        data_file_path = os.path.join(parameters['homepath'], dataDirectory + date + filename_addition + ".csv")
        if os.path.isfile(data_file_path):
            with open(data_file_path) as dailyFile:
                try:
                    daily_file_reader = csv.reader(dailyFile)
                except IOError:
                    logger.info("No data-file for " + str(date) + "!")
                    continue
                fieldnames = []
                for csvRow in daily_file_reader:
                    if daily_file_reader.line_num == 1:
                        # Get all the metric names
                        fieldnames = csvRow
                        for i in range(0, len(fieldnames)):
                            if fieldnames[i] == "timestamp":
                                timestamp_index = i
                    elif daily_file_reader.line_num > 1:
                        # skip lines which are already sent
                        try:
                            if long(csvRow[timestamp_index]) < long(startTimeEpoch):
                                continue
                        except ValueError:
                            continue
                        # Read each line from csv and generate a json
                        current_csv_row_data = {}
                        for i in range(0, len(csvRow)):
                            if fieldnames[i] == "timestamp":
                                new_prev_end_time_epoch = csvRow[timestamp_index]
                                current_csv_row_data[fieldnames[i]] = csvRow[i]
                            else:
                                # fix incorrectly named columns
                                colname = str(fieldnames[i])
                                if colname.find("]") == -1:
                                    colname = colname + "[" + parameters['hostname'] + "]"
                                if colname.find(":") == -1:
                                    colname = colname + ":" + str(get_index_for_column_name(fieldnames[i]))
                                current_csv_row_data[colname] = csvRow[i]
                        metric_data.append(current_csv_row_data)
    return new_prev_end_time_epoch


def process_replay(file_path):
    if os.path.isfile(file_path):
        logger.info("Replaying file: " + file_path)
        # log file replay processing
        if parameters['mode'] == "logFileReplay":
            output = subprocess.check_output(
                'cat ' + file_path + ' | jq -c ".[]" > ' + file_path + ".mod",
                shell=True)
            with open(file_path + ".mod") as logfile:
                line_count = 0
                chunk_count = 0
                current_row = []
                start_time = time.time()
                for line in logfile:
                    if line_count == parameters['chunkLines']:
                        logger.debug("--- Chunk creation time: %s seconds ---" % (time.time() - start_time))
                        send_data(current_row, file_path, None)
                        current_row = []
                        chunk_count += 1
                        line_count = 0
                        start_time = time.time()
                    current_row.append(json.loads(line.rstrip()))
                    line_count += 1
                if len(current_row) != 0:
                    logger.debug("--- Chunk creation time: %s seconds ---" % (time.time() - start_time))
                    send_data(current_row, file_path, None)
                    chunk_count += 1
                logger.debug("Total chunks created: " + str(chunk_count))
            try:
                subprocess.check_output("rm " + file_path + ".mod", shell=True)
            except subprocess.CalledProcessError:
                logger.error("Failed to rm file " + file_path + ".mod")
        else:  # metric file replay processing
            with open(file_path) as metricFile:
                metric_csv_reader = csv.reader(metricFile)
                to_send_metric_data = []
                fieldnames = []
                current_line_count = 1
                chunk_count = 0
                min_timestamp_epoch = 0
                max_timestamp_epoch = -1
                for row in metric_csv_reader:
                    if metric_csv_reader.line_num == 1:
                        # Get all the metric names from header
                        fieldnames = row
                        # get index of the timestamp column
                        for i in range(0, len(fieldnames)):
                            if fieldnames[i] == "timestamp":
                                timestampIndex = i
                    elif metric_csv_reader.line_num > 1:
                        # Read each line from csv and generate a json
                        current_row = {}
                        if current_line_count == parameters['chunkLines']:
                            send_data([to_send_metric_data, min_timestamp_epoch, max_timestamp_epoch], file_path, chunk_count + 1)
                            to_send_metric_data = []
                            current_line_count = 0
                            chunk_count += 1
                        for i in range(0, len(row)):
                            if fieldnames[i] == "timestamp":
                                current_row[fieldnames[i]] = row[i]
                                if min_timestamp_epoch == 0 or min_timestamp_epoch > long(row[i]):
                                    min_timestamp_epoch = long(row[i])
                                if max_timestamp_epoch == 0 or max_timestamp_epoch < long(row[i]):
                                    max_timestamp_epoch = long(row[i])
                            else:
                                colname = fieldnames[i]
                                if colname.find("]") == -1:
                                    colname = colname + "[-]"
                                if colname.find(":") == -1:
                                    groupid = i
                                    colname = colname + ":" + str(groupid)
                                current_row[colname] = row[i]
                        to_send_metric_data.append(current_row)
                        current_line_count += 1
                # send final chunk
                if len(to_send_metric_data) != 0:
                    send_data([to_send_metric_data, min_timestamp_epoch, max_timestamp_epoch], file_path, chunk_count + 1)
                    chunk_count += 1
                logger.debug("Total chunks created: " + str(chunk_count))


def set_logger_config(level):
    """Set up logging according to the defined log level"""
    # Get the root logger
    logger_obj = logging.getLogger(__name__)
    # Have to set the root logger level, it defaults to logging.WARNING
    logger_obj.setLevel(level)
    # route INFO and DEBUG logging to stdout from stderr
    logging_handler_out = logging.StreamHandler(sys.stdout)
    logging_handler_out.setLevel(logging.DEBUG)
    # create a logging format
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(process)d - %(threadName)s - %(levelname)s - %(message)s')
    logging_handler_out.setFormatter(formatter)
    logger_obj.addHandler(logging_handler_out)
    logging_handler_err = logging.StreamHandler(sys.stderr)
    logging_handler_err.setLevel(logging.WARNING)
    logger_obj.addHandler(logging_handler_err)
    return logger_obj


class LessThanFilter(logging.Filter):
    def __init__(self, exclusive_maximum, name=""):
        super(LessThanFilter, self).__init__(name)
        self.max_level = exclusive_maximum

    def filter(self, record):
        # non-zero return means we log this message
        return 1 if record.levelno < self.max_level else 0


def get_file_list_for_directory(root_path):
    file_list = []
    for path, subdirs, files in os.walk(root_path):
        for name in files:
            if parameters['agentType'] == "metricFileReplay" and "csv" in name:
                file_list.append(os.path.join(path, name))
            if parameters['agentType'] == "LogFileReplay" and "json" in name:
                file_list.append(os.path.join(path, name))
    return file_list


if __name__ == '__main__':
    prog_start_time = time.time()
    dataDirectory = 'data/'
    parameters = get_parameters()
    log_level = parameters['log_level']
    logger = set_logger_config(log_level)

    agent_config_vars = get_agent_config_vars()
    reporting_config_vars = get_reporting_config_vars()

    if parameters['agentType'] == "hypervisor":
        import urllib
    else:
        import requests

    # locate time range and date range
    prevEndtimeEpoch = reporting_config_vars['prev_endtime']
    newPrevEndtimeEpoch = 0
    startTimeEpoch = 0
    startTimeEpoch = update_data_start_time()

    if parameters['inputFile'] is None and parameters['logFolder'] is None:
        process_streaming(newPrevEndtimeEpoch)
    else:
        if parameters['logFolder'] is None:
            inputFilePath = os.path.join(parameters['homepath'], parameters['inputFile'])
            process_replay(inputFilePath)
        else:
            fileList = get_file_list_for_directory(parameters['logFolder'])
            for filePath in fileList:
                process_replay(filePath)

    logger.info("--- Total runtime: %s seconds ---" % (time.time() - prog_start_time))
    exit(0)