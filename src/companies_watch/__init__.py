from companies_watch.config import get_settings


def main() -> None:
    settings = get_settings()
    print(settings.database_url)
    print(settings)