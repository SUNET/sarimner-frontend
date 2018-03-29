Projekt Särimner frontend
=========================

Särimner frontend nodes use BGP anycast to make websites more reliable and
more DDoS resistant.

Optinally, Varnish caches can be deployed on the frontend nodes to make
the websites remain available in case of backend failures.

This repository holds scripts, examples and documentation for the parts
common for different organisations running Särimner frontend nodes. It
does not contain 'the whole thing' because different organisations will
have different host management systems.


Getting started
---------------
If the documentation that has yet to be written is too long for you, this
is a quick walk through of what should be needed:

1. Set up two Docker-capable frontend servers. For limited testing, VMs with 2GB of RAM is enough.
   Versions tested:
     * ubuntu 16.04
     * docker-ce 18.02
     * docker-compose 1.15.0
2. Copy the [scripts directory](/scripts) to /opt/frontend/scripts

3. Copy the [example config](/examples/config) to /opt/frontend/config.
   Adapt the 'www' instance to some web site of yours (files now in /opt/frontend/config/www).

4. Set up e.g. systemd to start the 'www' instance using docker-compose.
   See [systemd service example](/examples/systemd) and [docker-compose example](/examples/docker).

5. Repeat step 3-4 for any additional instances you want to run.

6. Set up exabgp (one instance per frontend) to talk BGP with your routers.
   See [exabgp example](/examples/exabgp).

7. If running Varnish, create the file /opt/frontend/config/common/default.vcl.
   See [example varnish config](/examples/varnish/default.vcl).

8. Start everything. Watch syslog and docker-compose logs.
