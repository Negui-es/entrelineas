"""Windows production origin for an existing, locally installed Cloudflare Tunnel."""
import argparse


def main():
    parser = argparse.ArgumentParser(description="Servidor local para el túnel de Entrelíneas")
    parser.add_argument("--port", type=int, default=18743)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("El puerto debe estar entre 1024 y 65535.")

    from entrelineas.wsgi import application
    from django.conf import settings
    if settings.DEBUG:
        parser.error("El servidor publicado requiere DEBUG=false en .env.")

    from waitress import serve
    serve(application, host="127.0.0.1", port=args.port, threads=8,
          trusted_proxy="127.0.0.1", trusted_proxy_count=1,
          trusted_proxy_headers={"x-forwarded-proto", "x-forwarded-for"},
          clear_untrusted_proxy_headers=True, ident="Entrelineas",
          # Allow multipart headers around the importer's 5 MB CSV limit.
          max_request_body_size=6 * 1024 * 1024)


if __name__ == "__main__":
    main()
