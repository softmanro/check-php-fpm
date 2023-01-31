#!/usr/bin/env python3

# Created by Liviu Andreicut, based on the following article:
# https://sleeplessbeastie.eu/2019/04/01/how-to-display-php-fpm-pool-information-using-unix-socket-and-python-script/
#
"""
Nagios PHP-FPM check script
"""

import sys
import socket
import struct
import json
import argparse

LISTEN_QUEUE_WARNING = 5
LISTEN_QUEUE_CRITICAL = 10

ACTIVE_PROCESSES_PCT_WARNING = 70
ACTIVE_PROCESSES_PCT_CRITICAL = 90

DEFAULT_FPM_SOCKET_PATH = "/run/php-fpm/www.sock"
DEFAULT_FPM_STATUS_PATH = "/status"

class FCGIStatusClient:
    """
    Class implementing Fast CGI specification
    """
    # FCGI protocol version
    FCGI_VERSION = 1

    # FCGI record types
    FCGI_BEGIN_REQUEST = 1
    FCGI_PARAMS = 4

    # FCGI roles
    FCGI_RESPONDER = 1

    # FCGI header length
    FCGI_HDR_LENGTH = 8

    fcgi_begin_request = None
    fcgi_params = None
    raw_status_data = None
    status_data = None

    def __init__( self, socket_path = DEFAULT_FPM_SOCKET_PATH, socket_timeout = 1.0,
                  status_path = DEFAULT_FPM_STATUS_PATH ):
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket_path = socket_path
        self.set_socket_timeout(socket_timeout)
        self.status_path = status_path
        self.request_id = 1

        self.params = {
            "SCRIPT_NAME": status_path,
            "SCRIPT_FILENAME": status_path,
            "QUERY_STRING": "",
            "REQUEST_METHOD": "GET",
        }

    def set_socket_timeout(self, timeout):
        self.socket_timeout = timeout
        self.socket.settimeout(self.socket_timeout)

    def connect(self):
        try:
            self.socket.connect(self.socket_path)
        except:
            print("Unable to connect to php-fpm socket, OS error: " + str(sys.exc_info()[1]))
            sys.exit(3)

    def close(self):
        self.socket.close()

    def define_begin_request(self):
        fcgi_begin_request = struct.pack("!HB5x", self.FCGI_RESPONDER, 0)
        fcgi_hdr        = struct.pack("!BBHHBx", self.FCGI_VERSION, self.FCGI_BEGIN_REQUEST,
                                          self.request_id, len(fcgi_begin_request), 0)
        self.fcgi_begin_request = fcgi_hdr + fcgi_begin_request

    def define_params(self):
        params = []
        for name, value in self.params.items():
            params.append(chr(len(name)) + chr(len(value)) + name + value)

        params             = ''.join(params)
        params_length      = len(params)
        params_padding_req = params_length & 7
        params_padding     = b'\x00' * params_padding_req

        fcgi_hdr_start = struct.pack("!BBHHBx", self.FCGI_VERSION, self.FCGI_PARAMS, \
                                         self.request_id, params_length , params_padding_req)
        fcgi_hdr_end   = struct.pack("!BBHHBx", self.FCGI_VERSION, self.FCGI_PARAMS, \
                                         self.request_id, 0, 0)
        self.fcgi_params = fcgi_hdr_start  + params.encode() + params_padding + fcgi_hdr_end

    def execute(self):
        try:
            self.socket.send(self.fcgi_begin_request)
            self.socket.send(self.fcgi_params)

            header = self.socket.recv(self.FCGI_HDR_LENGTH)
            fcgi_version, request_type, request_id, \
            request_length, request_padding = struct.unpack("!BBHHBx", header)

            if request_type == 6:
                self.raw_status_data = self.socket.recv(request_length)
            elif request_type == 7:
                raise Exception("Received an error packet.")
            else:
                raise Exception("Received unexpected packet type.")
        except:
            print("Unable to connect to php-fpm socket, OS error: " + str(sys.exc_info()[1]))
            sys.exit(3)
        self.status_data = self.raw_status_data.decode().split("\r\n\r\n")[1]

    def make_request(self):
        self.define_begin_request()
        self.define_params()
        self.connect()
        self.execute()
        self.close()

    def print_status(self):
        print(self.status_data)

    def output_json_status(self):
        out_list = {}
        for line in self.status_data.splitlines():
            params = line.split(":")
            param  = params[0]
            for values in params[1].split():
                out_list[param] = values
        return json.dumps(out_list)

parser = argparse.ArgumentParser(description='Simple PHP-FPM status check script')
parser.add_argument('-s', '--socket-path', help='Unix socket path of the php-fpm pool. ' + \
                    'Current user requires permissions to access it. Defaults to ' + \
                    DEFAULT_FPM_SOCKET_PATH + '.')
parser.add_argument('-p', '--status-path', help='The path defined in php-fpm pool ' + \
                    'configuration (pm.status_path). Defaults to ' + \
                    DEFAULT_FPM_STATUS_PATH + '.')
parser.add_argument('-qw', '--queue-warning', type=int, help='Warning threshold of ' + \
                    'requests in listen queue. Defaults to ' + \
                    str(LISTEN_QUEUE_WARNING) + '.')
parser.add_argument('-qc', '--queue-critical', type=int, help='Critical threshold of ' + \
                    'requests in listen queue. Defaults to ' + str(LISTEN_QUEUE_CRITICAL) + '.')
parser.add_argument('-pw', '--processes-warning', type=int, help='Warning threshold of ' + \
                    'total processes vs active ones. Defaults to ' + \
                    str(ACTIVE_PROCESSES_PCT_WARNING) + '%%.')
parser.add_argument('-pc', '--processes-critical', type=int, help='Critical threshold of ' + \
                    'total processes vs active ones. Defaults to ' + \
                    str(ACTIVE_PROCESSES_PCT_CRITICAL) + '%%.')

args = parser.parse_args()

fpm_socket_path = DEFAULT_FPM_SOCKET_PATH
fpm_status_path = DEFAULT_FPM_STATUS_PATH
listen_queue_warning = LISTEN_QUEUE_WARNING
listen_queue_critical = LISTEN_QUEUE_CRITICAL
active_percent_warning = ACTIVE_PROCESSES_PCT_WARNING
active_percent_critical = ACTIVE_PROCESSES_PCT_CRITICAL

if args.socket_path is not None:
    fpm_socket_path = args.socket_path

if args.status_path is not None:
    fpm_status_path = args.status_path

if args.queue_warning is not None:
    listen_queue_warning = args.queue_warning

if args.queue_critical is not None:
    listen_queue_critical = args.queue_critical

if args.processes_warning is not None:
    active_percent_warning = args.processes_warning

if args.processes_critical is not None:
    active_percent_critical = args.processes_critical

if listen_queue_warning >= listen_queue_critical:
    print("Warning threshold should be less than critical.")
    sys.exit(3)

if active_percent_warning >= active_percent_critical:
    print("Warning threshold should be less than critical.")
    sys.exit(3)

if active_percent_warning < 0 or active_percent_warning > 100:
    print("Warning threshold percentage should be between 0 and 100.")
    sys.exit(3)

if active_percent_critical < 0 or active_percent_critical > 100:
    print("Warning threshold percentage should be between 0 and 100.")
    sys.exit(3)

fcgi_client = FCGIStatusClient( socket_path = fpm_socket_path, status_path = fpm_status_path )
fcgi_client.make_request()

fpm_status = json.loads(fcgi_client.output_json_status())

listen_queue = int(fpm_status["listen queue"])
if listen_queue >= listen_queue_warning < listen_queue_critical:
    print("Listen queue warning: " + str(listen_queue) + " requests in queue")
    sys.exit(1)
elif listen_queue >= listen_queue_critical:
    print("Listen queue critical: " + str(listen_queue) + " requests in queue")
    sys.exit(2)

active_procs = int(fpm_status["active processes"])
total_procs = int(fpm_status["total processes"])
used_pct = active_procs/total_procs*100

if used_pct >= active_percent_warning < active_percent_critical:
    print("Used php-fpm workers percent warning: " + str(used_pct) + "%")
    sys.exit(1)
elif used_pct >= active_percent_critical:
    print("Used php-fpm workers percent warning: " + str(used_pct) + "%")
    sys.exit(2)

print("php-fpm status normal: " + str(listen_queue) + " requests in queue, " + \
      str(active_procs) + "/" + str(total_procs) + " used workers")

sys.exit(0)
