#!/bin/bash
#
# Start script for haproxy container, managing startup process and automatic reload
# on config change (detected using inotify events triggering on MOVED_TO).
#

HAPROXYCFG=${HAPROXYCFG-'/etc/haproxy/haproxy.cfg'}
HAPROXYWAITIF=${HAPROXYWAITIF-'20'}
HAPROXYWAITCFG=${HAPROXYWAITCFG-'10'}
HAPROXYWAITCONTAINER=${HAPROXYWAITCONTAINER-'10'}

if [[ $WAIT_FOR_INTERFACE ]]; then
    for i in $(seq "${HAPROXYWAITIF}"); do
	ip link ls dev "$WAIT_FOR_INTERFACE" 2>&1 | grep -q 'state UP' && break
	echo "$0: Waiting for interface ${WAIT_FOR_INTERFACE} (${i}/${HAPROXYWAITIF})"
	sleep 1
    done

    if ! ip link ls dev "$WAIT_FOR_INTERFACE" | grep -q 'state UP'; then
	echo "$0: Interface ${WAIT_FOR_INTERFACE} not found after ${HAPROXYWAITIF} seconds - exiting"
	echo "$0: The interface should have been configured by the script 'configure-container-network'"
	echo "$0: that should have been executed by the systemd service for this frontend instance."
	echo "$0: Investigate why it failed, or didn't start in time before this script gave up."
	exit 1
    fi

    echo "$0: Interface ${WAIT_FOR_INTERFACE} is UP:"
    ip addr list "$WAIT_FOR_INTERFACE"
fi

for i in $(seq "${HAPROXYWAITCFG}"); do
    test -f "${HAPROXYCFG}" && break
    echo "$0: Waiting for haproxy config file ${HAPROXYCFG} (${i}/${HAPROXYWAITCFG})"
    sleep 1
done

if [ ! -f "${HAPROXYCFG}" ]; then
    echo "$0: haproxy config not found after ${HAPROXYWAITCFG} seconds: ${HAPROXYCFG} - exiting"
    echo "$0: The haproxy config file should have been created by the 'config' container for this frontend instance"
    exit 1
fi

if [[ $WAIT_FOR_CONTAINER ]]; then
    seen=0
    for i in $(seq "${HAPROXYWAITCONTAINER}"); do
	ping -c 1 "${WAIT_FOR_CONTAINER}" > /dev/null 2>&1 && seen=1
	test $seen == 1 && break
	echo "$0: Waiting for container ${WAIT_FOR_CONTAINER} to appear (${i}/${HAPROXYWAITCONTAINER})"
	sleep 1
    done
    if [[ $seen != 1 ]]; then
	echo "$0: Container ${WAIT_FOR_CONTAINER} not present after ${HAPROXYWAITCONTAINER} seconds"
	exit 1
    fi
fi


echo "$0: Checking config: ${HAPROXYCFG}"

config_ok=0
/usr/sbin/haproxy -c -f "${HAPROXYCFG}" && config_ok=1
if [ $config_ok != 1 ]; then
    echo "$0: Config ${HAPROXYCFG} NOT OK, exiting"
    exit 1
fi

echo "$0: Config ${HAPROXYCFG} checked OK, starting haproxy"
if [ -x /usr/sbin/haproxy-systemd-wrapper ]; then
    # haproxy 1.7
    /usr/sbin/haproxy-systemd-wrapper -p /run/haproxy.pid -f "${HAPROXYCFG}" &
    pid=$!
else
    # haproxy 1.8+
    /usr/sbin/haproxy "$@" -p /run/haproxy.pid -f "${HAPROXYCFG}" &
    pid=$!
fi
pid2=0

term_handler() {
    echo "$0: Received SIGTERM, shutting down ${pid}, ${pid2}"
    if [ $pid -ne 0 ]; then
	kill -SIGTERM "$pid"
	wait "$pid"
    fi
    if [ $pid2 -ne 0 ]; then
	kill -SIGTERM "$pid2"
	wait "$pid2"
    fi
    exit 143; # 128 + 15 -- SIGTERM
}

trap 'term_handler' SIGTERM


while true; do
    echo "$0: Waiting for ${HAPROXYCFG} to be moved-to"

    # Block until an inotify event says that the config file was replaced
    inotifywait -q -e moved_to "${HAPROXYCFG}" &
    pid2=$!
    wait $pid2

    echo "$0: Move-to event triggered, checking config: ${HAPROXYCFG}"
    config_ok=1
    /usr/sbin/haproxy -c -f "${HAPROXYCFG}" || config_ok=0
    if [ $config_ok = 1 ]; then
	echo "$0: Config ${HAPROXYCFG} checked OK, gracefully restarting haproxy"
	/usr/sbin/haproxy "$@" -p /run/haproxy.pid -f "${HAPROXYCFG}" -sf "$(cat /run/haproxy.pid)"
	echo "$0: haproxy gracefully reloaded"
    else
	echo "$0: Config ${HAPROXYCFG} NOT OK"
    fi
    sleep 1  # spin control
done
