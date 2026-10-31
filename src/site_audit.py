"""Site trust and sustainability estimates used by the audit panels."""
import socket, ssl
from urllib.parse import urlparse

def certificate_audit(url):
    parsed = urlparse(url if '://' in url else 'https://' + url)
    if parsed.scheme != 'https':
        return {'secure': False, 'error': 'URL is not HTTPS'}
    host = parsed.hostname; port = parsed.port or 443
    context = ssl.create_default_context()
    try:
        with socket.create_connection((host, port), timeout=10) as sock:
            with context.wrap_socket(sock, server_hostname=host) as tls:
                cert = tls.getpeercert()
                return {'secure': True, 'verified': True, 'subject': cert.get('subject'),
                        'issuer': cert.get('issuer'), 'expires': cert.get('notAfter'),
                        'protocol': tls.version()}
    except ssl.SSLCertVerificationError as error:
        return {'secure': True, 'verified': False, 'error': str(error)}
    except Exception as error:
        return {'secure': True, 'verified': False, 'error': str(error)}

def carbon_estimate(bytes_transferred, requests_count=1, green_hosting=False):
    # Transparent estimate based on the Sustainable Web Design model.
    gb = max(0.0, float(bytes_transferred or 0)) / (1024 ** 3)
    grams = gb * (0.81 if green_hosting else 1.76) + max(0, int(requests_count)) * 0.0002
    return {'bytes': int(bytes_transferred or 0), 'requests': int(requests_count),
            'green_hosting': bool(green_hosting), 'estimated_grams_co2': round(grams, 6),
            'method': 'transfer-size estimate; not a provider-certified measurement'}
