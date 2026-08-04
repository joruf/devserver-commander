"""Name the service behind a TCP port.

Resolution happens in two steps. A curated table comes first, because it carries
readable names and covers development tooling that the system port database does
not know (Vite, Mailpit, Ollama, ...). Everything else falls back to
``/etc/services`` via :func:`socket.getservbyport`, which adds the several hundred
registered names shipped with the system.

A name resolved this way describes what *usually* listens on that port. It is a
convention, not proof of what is running.
"""

import socket
from typing import Dict, Optional

WELL_KNOWN_PORTS: Dict[int, str] = {
    # Databases
    1433: "Microsoft SQL Server",
    1521: "Oracle Database",
    3050: "Firebird",
    3306: "MySQL / MariaDB",
    33060: "MySQL X Protocol",
    5432: "PostgreSQL",
    6432: "PgBouncer",
    5984: "CouchDB",
    7687: "Neo4j (Bolt)",
    8086: "InfluxDB",
    9042: "Cassandra",
    27017: "MongoDB",
    27018: "MongoDB (shard)",
    27019: "MongoDB (config server)",
    50000: "IBM Db2",
    # Caches and key-value stores
    6379: "Redis",
    6380: "Redis (alternate)",
    11211: "Memcached",
    2379: "etcd (client)",
    2380: "etcd (peer)",
    8500: "Consul",
    # Search
    9200: "Elasticsearch / OpenSearch (HTTP)",
    9300: "Elasticsearch (transport)",
    5601: "Kibana",
    7700: "Meilisearch",
    8983: "Apache Solr",
    9308: "Manticore Search",
    # Message brokers and streaming
    1883: "MQTT",
    8883: "MQTT (TLS)",
    4222: "NATS",
    5672: "RabbitMQ (AMQP)",
    15672: "RabbitMQ (management)",
    9092: "Apache Kafka",
    2181: "ZooKeeper",
    # Mail
    25: "SMTP",
    465: "SMTPS",
    587: "SMTP (submission)",
    110: "POP3",
    995: "POP3S",
    143: "IMAP",
    993: "IMAPS",
    1025: "MailHog / Mailpit (SMTP)",
    8025: "MailHog / Mailpit (web UI)",
    1080: "MailCatcher (web UI)",
    # Web servers and proxies
    80: "HTTP",
    443: "HTTPS",
    8080: "HTTP (alternate)",
    8443: "HTTPS (alternate)",
    3128: "Squid proxy",
    9000: "PHP-FPM / MinIO",
    9001: "Supervisor / MinIO console",
    # Development servers
    1313: "Hugo",
    3000: "Node.js / React dev server",
    3001: "Node.js dev server (alternate)",
    4200: "Angular dev server",
    4321: "Astro",
    5000: "Flask / ASP.NET dev server",
    5173: "Vite",
    5174: "Vite (alternate)",
    8000: "Django / PHP dev server",
    8081: "HTTP dev server (alternate)",
    9229: "Node.js inspector",
    # Observability
    3100: "Grafana Loki",
    3200: "Grafana Tempo",
    9090: "Prometheus",
    9093: "Alertmanager",
    9100: "Prometheus node exporter",
    16686: "Jaeger UI",
    # Containers and orchestration
    2375: "Docker (HTTP)",
    2376: "Docker (TLS)",
    6443: "Kubernetes API server",
    10250: "kubelet",
    # AI tooling
    11434: "Ollama",
    # Remote access and file sharing
    22: "SSH",
    139: "SMB (NetBIOS)",
    445: "SMB",
    2049: "NFS",
    3389: "RDP",
    5900: "VNC",
    8384: "Syncthing (web UI)",
    # System services
    53: "DNS",
    111: "rpcbind",
    123: "NTP",
    323: "chrony",
    631: "IPP / CUPS",
    5353: "mDNS",
    9050: "Tor SOCKS proxy",
    # Version control
    9418: "Git daemon",
}


def service_name_for_port(port: int) -> Optional[str]:
    """
    Return the service conventionally reachable on a TCP port.

    :param port: TCP port number
    :return: Service name, or None when the port is not a known one
    """
    curated = WELL_KNOWN_PORTS.get(port)
    if curated is not None:
        return curated

    try:
        return socket.getservbyport(port, "tcp")
    except (OSError, OverflowError, TypeError, ValueError):
        return None
