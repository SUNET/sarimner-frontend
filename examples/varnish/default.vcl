vcl 4.0;
# Based on: https://github.com/mattiasgeniar/varnish-4.0-configuration-templates/blob/master/default.vcl

import std;
import directors;

backend server1 { # Define one backend
  .host = "haproxy";    # IP or Hostname of backend
  .port = "1080";           # Port Apache or whatever is listening
  .max_connections = 300; # That's it

#  .probe = {
#    #.url = "/"; # short easy way (GET /)
#    # We prefer to only do a HEAD /
#    .request =
#      "HEAD / HTTP/1.1"
#      "Host: localhost"
#      "Connection: close"
#      "User-Agent: Varnish Health Probe";
#
#    .interval  = 5s; # check the health of each backend every 5 seconds
#    .timeout   = 1s; # timing out after 1 second.
#    .window    = 5;  # If 3 out of the last 5 polls succeeded the backend is considered healthy, otherwise it will be marked as sick
#    .threshold = 3;
#  }

GET THE REST OF THIS FILE FROM https://github.com/mattiasgeniar/varnish-4.0-configuration-templates/blob/master/default.vcl
