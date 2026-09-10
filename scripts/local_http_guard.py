"""Access boundaries for the loopback-only dashboard."""
from pathlib import Path
from urllib.parse import unquote, urlsplit


class LocalHTTPGuard:
    def parse_request(self):
        if not super().parse_request():
            return False
        host = urlsplit('http://' + self.headers.get('Host', ''))
        try:
            valid = host.hostname in {'127.0.0.1', 'localhost', '::1'} and host.port == self.server.server_port
        except ValueError:
            valid = False
        if not valid:
            self.send_error(403, 'Local host required')
            return False
        origin = self.headers.get('Origin')
        if origin:
            parsed = urlsplit(origin)
            if parsed.scheme != 'http' or parsed.netloc != host.netloc:
                self.send_error(403, 'Same origin required')
                return False
        if self.command == 'POST' and (self.headers.get('Sec-Fetch-Site') == 'cross-site' or self.headers.get_content_type() != 'application/json'):
            self.send_error(403, 'Same origin JSON required')
            return False
        return True

    def send_head(self):
        path = unquote(urlsplit(self.path).path)
        parts = Path(path).parts
        root = Path(self.directory).resolve()
        resolved = Path(self.translate_path(self.path)).resolve()
        if resolved.is_relative_to(root):
            parts = (*parts, *resolved.relative_to(root).parts)
        if (any(part.startswith('.') or part in {'local_inputs', 'logs', '__pycache__'} for part in parts)
                or not resolved.is_relative_to(root)):
            self.send_error(403, 'Private path')
            return None
        return super().send_head()

    def list_directory(self, path):
        self.send_error(403, 'Directory listing disabled')
        return None
