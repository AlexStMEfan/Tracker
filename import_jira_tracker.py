import os
import logging
import csv
from jira import JIRA
from yandex_tracker_client import TrackerClient
import tempfile
from dotenv import load_dotenv
from datetime import datetime

# Загрузка переменных окружения из файла .env
load_dotenv()

# Конфигурация
JIRA_URL = os.getenv('JIRA_URL')
JIRA_USER = os.getenv('JIRA_USER')
JIRA_API_TOKEN = os.getenv('JIRA_API_TOKEN')
ORG_ID = os.getenv('ORG_ID')  # Идентификатор обычной организации в Yandex Tracker
CLOUD_ORG_ID = os.getenv('CLOUD_ORG_ID')  # Идентификатор облачной организации в Yandex Cloud
TOKEN = os.getenv('TOKEN')  # Токен для доступа к Yandex Tracker
PER_PAGE = 1000  # Количество задач на странице
USER_MAPPING_FILE = 'user_mapping.csv'  # Файл для сопоставления пользователей

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Функция для инициализации клиента Jira
def init_jira_client(url, user, api_token):
    try:
        jira_client = JIRA(server=url, basic_auth=(user, api_token))
        logger.info("Jira client initialized successfully.")
        return jira_client
    except Exception as e:
        logger.error(f"Ошибка инициализации клиента Jira: {e}")
        raise

# Функция для инициализации клиента Яндекс Трекера
def init_tracker_client(org_id, cloud_org_id, token):
    if not org_id and not cloud_org_id:
        logger.error("Необходимо указать либо ORG_ID, либо CLOUD_ORG_ID.")
        raise ValueError("Необходимо указать либо ORG_ID, либо CLOUD_ORG_ID.")
    if org_id:
        logger.info(f"Используется обычная организация с ID: {org_id}")
        return TrackerClient(token=token, org_id=org_id)
    elif cloud_org_id:
        logger.info(f"Используется облачная организация с ID: {cloud_org_id}")
        return TrackerClient(token=token, cloud_org_id=cloud_org_id)

# Чтение файла сопоставления пользователей
def read_user_mapping(file_path):
    if not os.path.isfile(file_path):
        logger.error(f"Файл сопоставления пользователей {file_path} не найден.")
        raise FileNotFoundError(f"Файл сопоставления пользователей {file_path} не найден.")
    try:
        with open(file_path, "r") as file:
            reader = csv.DictReader(file)
            if 'jira_user' not in reader.fieldnames or 'tracker_user' not in reader.fieldnames:
                logger.error(f"Файл {file_path} не содержит необходимых столбцов.")
                raise ValueError(f"Файл {file_path} не содержит необходимых столбцов.")
            user_mapping = {}
            for row in reader:
                if row['jira_user'] in user_mapping:
                    logger.warning(f"Дублирующийся UID пользователя {row['jira_user']} в файле {file_path}.")
                user_mapping[row['jira_user']] = row['tracker_user']
        logger.info("Файл сопоставления пользователей загружен успешно.")
        return user_mapping
    except Exception as e:
        logger.error(f"Ошибка чтения файла сопоставления пользователей {file_path}: {e}")
        raise

# Пагинация для получения задач из Jira
def fetch_issues_with_pagination(jira_client, jql_query, per_page=1000):
    issues = []
    start_at = 0
    while True:
        batch = jira_client.search_issues(jql_query, startAt=start_at, maxResults=per_page)
        issues.extend(batch)
        if len(batch) < per_page:
            break
        start_at += per_page
    logger.info(f"Получено {len(issues)} задач из Jira.")
    return issues

# Экспорт данных из Jira
def export_data_from_jira(jira_client):
    try:
        projects = jira_client.projects()
        issues = []
        for project in projects:
            issues.extend(fetch_issues_with_pagination(jira_client, f'project = "{project.key}"'))
        logger.info(f"Экспорт данных из Jira завершен: {len(projects)} проектов, {len(issues)} задач.")
        return projects, issues
    except Exception as e:
        logger.error(f"Ошибка экспорта данных из Jira: {e}")
        raise

# Преобразование данных из Jira в формат Яндекс Трекера
def transform_data(projects, issues, user_mapping):
    tracker_queues = {}
    tracker_issues = []
    for project in projects:
        queue_key = project.key
        tracker_queue = {
            "name": project.name,
            "key": queue_key,
        }
        tracker_queues[queue_key] = tracker_queue
    
    for issue in issues:
        assignee_key = issue.fields.assignee.key if hasattr(issue.fields, 'assignee') and issue.fields.assignee else None
        reporter_key = issue.fields.reporter.key if hasattr(issue.fields, 'reporter') and issue.fields.reporter else None
        
        # Сопоставление пользователей
        assignee_key = user_mapping.get(assignee_key, assignee_key)
        reporter_key = user_mapping.get(reporter_key, reporter_key)
        
        tracker_issue = {
            "summary": issue.fields.summary,
            "description": issue.fields.description,
            "assignee": assignee_key,
            "reporter": reporter_key,
            "status": issue.fields.status.name if hasattr(issue.fields, 'status') else None,
            "queue": issue.fields.project.key,
            "comments": [{"author": comment.author.key if hasattr(comment, 'author') and comment.author else None, "body": comment.body} 
                         for comment in issue.fields.comment.comments] if hasattr(issue.fields, 'comment') else [],
            "priority": issue.fields.priority.name if hasattr(issue.fields, 'priority') else None,
            "created": issue.fields.created if hasattr(issue.fields, 'created') else None,
            "updated": issue.fields.updated if hasattr(issue.fields, 'updated') else None,
            "labels": [label for label in issue.fields.labels] if hasattr(issue.fields, 'labels') else [],
            "attachments": issue.fields.attachment if hasattr(issue.fields, 'attachment') else [],
            "links": issue.fields.issuelinks if hasattr(issue.fields, 'issuelinks') else []
        }
        tracker_issues.append(tracker_issue)
    
    logger.info(f"Преобразовано {len(tracker_issues)} задач в формат Яндекс Трекера.")
    return tracker_queues, tracker_issues

# Функция для создания задачи в Яндекс Трекере
def create_issue(tracker_client, tracker_issue, queue):
    try:
        issue = tracker_client.issues.create(
            queue=queue.key,
            summary=tracker_issue["summary"],
            description=tracker_issue["description"],
            assignee=tracker_issue["assignee"],
            author=tracker_issue["reporter"],
            status=tracker_issue["status"],
            priority=tracker_issue.get("priority"),
            created=tracker_issue.get("created"),
            updated=tracker_issue.get("updated"),
            tags=tracker_issue.get("labels", [])
        )
        logger.info(f"Задача {tracker_issue['summary']} создана успешно в очереди {queue.key}.")
        return issue
    except Exception as e:
        logger.error(f"Ошибка создания задачи {tracker_issue['summary']} в очереди {queue.key}: {e}")
        raise

# Функция для добавления комментариев в задачу Яндекс Трекера
def add_comments_to_issue(tracker_client, issue, comments):
    for comment in comments:
        comment_author = comment["author"]
        if comment_author:
            try:
                tracker_client.users.get(comment_author)
                logger.info(f"Пользователь {comment_author} найден в Яндекс Трекере.")
            except Exception:
                logger.warning(f"Пользователь {comment_author} не найден в Яндекс Трекере.")
                comment_author = None
        try:
            tracker_client.issues[issue.key].comments.create(text=comment["body"], author=comment_author)
            logger.info(f"Комментарий успешно добавлен к задаче {issue.key}.")
        except Exception as e:
            logger.error(f"Ошибка добавления комментария к задаче {issue.key}: {e}")
            raise

# Функция для добавления вложений в задачу Яндекс Трекера
def add_attachments_to_issue(tracker_client, issue, attachments):
    for attachment in attachments:
        try:
            # Скачивание вложения из Jira
            attachment_content = attachment.get()
            attachment_filename = attachment.filename

            # Загрузка вложения в Яндекс Трекер без сохранения во временный файл
            tracker_client.issues[issue.key].attachments.upload(attachment_filename, content=attachment_content)
            logger.info(f"Вложение {attachment_filename} успешно загружено для задачи {issue.key}.")
        except Exception as e:
            logger.error(f"Ошибка загрузки вложения {attachment.filename} для задачи {issue.key}: {e}")
            raise

# Функция для добавления связей между задачами в Яндекс Трекере
def add_links_to_issue(tracker_client, issue, links):
    for link in links:
        try:
            linked_issue_key = link.outwardIssue.key if hasattr(link, 'outwardIssue') else link.inwardIssue.key
            linked_issue = tracker_client.issues.get(linked_issue_key)
            link_type = 'relates'  # или другой тип связи
            tracker_client.issues[issue.key].links.create(type=link_type, target=linked_issue.key)
            logger.info(f"Связь типа {link_type} создана для задачи {issue.key} с задачей {linked_issue.key}.")
        except Exception as e:
            logger.error(f"Ошибка создания связи для задачи {issue.key}: {e}")
            raise

# Импорт данных в Яндекс Трекер
def import_data_to_tracker(tracker_client, tracker_queues, tracker_issues, user_mapping):
    created_queues = {}
    created_users = set()

    # Создание очередей
    for tracker_queue in tracker_queues.values():
        try:
            queue = tracker_client.queues.get(tracker_queue["key"])
            created_queues[tracker_queue["key"]] = queue
            logger.info(f"Очередь {tracker_queue['name']} уже существует.")
        except Exception:
            try:
                queue = tracker_client.queues.create(
                    name=tracker_queue["name"],
                    key=tracker_queue["key"]
                )
                created_queues[tracker_queue["key"]] = queue
                logger.info(f"Создана очередь: {tracker_queue['name']}")
            except Exception as e:
                logger.error(f"Ошибка создания очереди {tracker_queue['name']}: {e}")
                raise

    # Создание задач
    for tracker_issue in tracker_issues:
        try:
            queue_key = tracker_issue["queue"]
            if queue_key not in created_queues:
                logger.warning(f"Очередь {queue_key} не найдена. Пропускаем задачу {tracker_issue['summary']}.")
                continue
            
            queue = created_queues[queue_key]
            
            # Проверка существования пользователей
            assignee = tracker_issue["assignee"]
            reporter = tracker_issue["reporter"]
            if assignee and assignee not in created_users:
                try:
                    tracker_client.users.get(assignee)
                    created_users.add(assignee)
                    logger.info(f"Пользователь {assignee} найден в Яндекс Трекере.")
                except Exception:
                    logger.warning(f"Пользователь {assignee} не найден в Яндекс Трекере.")
                    assignee = None
            
            if reporter and reporter not in created_users:
                try:
                    tracker_client.users.get(reporter)
                    created_users.add(reporter)
                    logger.info(f"Пользователь {reporter} найден в Яндекс Трекере.")
                except Exception:
                    logger.warning(f"Пользователь {reporter} не найден в Яндекс Трекере.")
                    reporter = None

            issue = tracker_client.issues.create(
                queue=queue.key,
                summary=tracker_issue["summary"],
                description=tracker_issue["description"],
                assignee=assignee,
                author=reporter,
                status=tracker_issue["status"],
                priority=tracker_issue.get("priority"),
                created=tracker_issue.get("created"),
                updated=tracker_issue.get("updated"),
                tags=tracker_issue.get("labels", [])
            )

            # Добавление комментариев
            if hasattr(tracker_issue, 'comments'):
                add_comments_to_issue(tracker_client, issue, tracker_issue["comments"])

            # Добавление вложений
            if hasattr(tracker_issue, 'attachments'):
                add_attachments_to_issue(tracker_client, issue, tracker_issue["attachments"])

            # Добавление связей между задачами
            if hasattr(tracker_issue, 'links'):
                add_links_to_issue(tracker_client, issue, tracker_issue["links"])

            logger.info(f"Задача {tracker_issue['summary']} успешно создана.")
        except Exception as e:
            logger.error(f"Ошибка создания задачи {tracker_issue['summary']}: {e}")
            raise

# Основная функция
def main():
    start_time = datetime.now()
    logger.info("Начало миграции данных из Jira в Яндекс Трекер.")

    try:
        jira_client = init_jira_client(JIRA_URL, JIRA_USER, JIRA_API_TOKEN)
        tracker_client = init_tracker_client(ORG_ID, CLOUD_ORG_ID, TOKEN)

        if not jira_client or not tracker_client:
            logger.error("Не удалось инициализировать клиенты.")
            return

        user_mapping = read_user_mapping(USER_MAPPING_FILE)
        projects, issues = export_data_from_jira(jira_client)
        if not projects or not issues:
            logger.error("Не удалось получить данные из Jira.")
            return

        tracker_queues, tracker_issues = transform_data(projects, issues, user_mapping)
        import_data_to_tracker(tracker_client, tracker_queues, tracker_issues, user_mapping)

        end_time = datetime.now()
        logger.info(f"Миграция завершена за {(end_time - start_time).total_seconds()} секунд.")
        logger.info(f"Обработано {len(tracker_issues)} задач.")
    except Exception as e:
        logger.critical(f"Ошибка при выполнении миграции: {e}")
        raise

if __name__ == "__main__":
    main()