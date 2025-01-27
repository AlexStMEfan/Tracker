from yandex_tracker_client import TrackerClient
import os
import logging
from collections import OrderedDict

# Конфигурация
ORG_ID = ''  # Идентификатор обычной организации в Yandex Tracker
CLOUD_ORG_ID = ''  # Идентификатор облачной организации в Yandex Cloud
TOKEN = ''  # Токен для доступа к Yandex Tracker
PER_PAGE = 1000  # Количество задач на странице

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Функция для записи данных в файл
def write_to_file(file_path, content):
    try:
        with open(file_path, "a") as file:
            file.write(content + "\n")
    except Exception as e:
        logging.error(f"Ошибка записи в файл {file_path}: {e}")

# Функция для чтения данных из файла
def read_file(file_path):
    if not os.path.isfile(file_path):
        logging.warning(f"Файл {file_path} не найден.")
        return []
    try:
        with open(file_path, "r") as file:
            return file.readlines()
    except Exception as e:
        logging.error(f"Ошибка чтения файла {file_path}: {e}")
        return []

# Инициализация клиента
def init_client(org_id, cloud_org_id, token):
    if org_id:
        return TrackerClient(token=token, org_id=org_id)
    elif cloud_org_id:
        return TrackerClient(token=token, cloud_org_id=cloud_org_id)
    else:
        raise ValueError("Either ORG_ID or CLOUD_ORG_ID must be provided.")

# Экспорт пользователей в файл from.txt
def export_users(client, file_path):
    try:
        all_users = client.users.get_all()
        if not all_users:
            logging.warning("Нет пользователей для экспорта.")
            return
    except Exception as e:
        logging.error(f"Ошибка получения пользователей: {e}")
        return
    if not os.path.isfile(file_path):
        try:
            with open(file_path, "w") as file:
                for user in all_users:
                    user_info = f"{user.uid} # {user.email} {user.display}"
                    file.write(user_info + "\n")
            logging.info(f"Пользователи экспортированы в файл '{file_path}'. Добавьте UID для замены и сохраните в 'to.txt'.")
        except Exception as e:
            logging.error(f"Ошибка создания файла {file_path}: {e}")
    else:
        logging.warning(f"Файл '{file_path}' уже существует.")

# Обработка задач из файла to.txt
def process_issues(client_from, client_to, old_uid, new_uid):
    def update_issues(filter_key):
        current_page = 1
        total_updated = 0
        while True:
            try:
                issues = client_from.issues.find(
                    filter={filter_key: old_uid},
                    per_page=PER_PAGE,
                    page=current_page
                )
                if not issues or current_page > issues.pages_count:
                    break
                logging.info(f"Страница {current_page}/{issues.pages_count}, всего задач: {issues._items_count}")
                for issue in issues:
                    try:
                        # Обновление задачи
                        if filter_key == "assignee":
                            client_to.issues[issue.key].update(assignee=new_uid)
                            logging.info(f"Задача {issue.key}: Обновлён исполнитель.")
                        elif filter_key == "createdBy":
                            client_to.issues[issue.key].update(author=new_uid)
                            logging.info(f"Задача {issue.key}: Обновлён автор.")
                        elif filter_key == "followers":
                            followers_update = {
                                'add': [new_uid],
                                'remove': [old_uid]
                            }
                            client_to.issues[issue.key].update(followers=followers_update)
                            logging.info(f"Задача {issue.key}: Обновлены подписчики.")
                        total_updated += 1
                    except Exception as e:
                        logging.error(f"Ошибка обновления задачи {issue.key}: {e}")
                current_page += 1
            except Exception as e:
                logging.error(f"Ошибка загрузки задач (страница {current_page}): {e}")
                break
        logging.info(f"Всего обновлено задач по фильтру '{filter_key}': {total_updated}")

    # Обработка задач
    logging.info("------ Задачи с исполнителем ------")
    update_issues("assignee")
    logging.info("------ Задачи с автором ------")
    update_issues("createdBy")
    logging.info("------ Задачи с подписчиками ------")
    update_issues("followers")

def main():
    while True:
        print("Выберите источник и цель:")
        print("1. Из обычной организации в облачную")
        print("2. Из облачной организации в обычную")
        choice = input("Введите ваш выбор (1/2): ")
        if choice == '1':
            source_client = init_client(ORG_ID, None, TOKEN)
            target_client = init_client(None, CLOUD_ORG_ID, TOKEN)
            break
        elif choice == '2':
            source_client = init_client(None, CLOUD_ORG_ID, TOKEN)
            target_client = init_client(ORG_ID, None, TOKEN)
            break
        else:
            logging.warning("Неверный выбор. Пожалуйста, выберите 1 или 2.")

    # Экспорт пользователей из источника
    export_users(source_client, "from.txt")

    # Проверка наличия файла to.txt
    if not os.path.isfile("to.txt"):
        logging.error("Файл 'to.txt' не найден. Создайте файл и добавьте UID для замены.")
        return
    lines = read_file("to.txt")
    if not lines:
        logging.warning("Файл 'to.txt' пуст. Ничего не будет обработано.")
        return

    # Удаление дубликатов в файле to.txt с сохранением порядка
    unique_lines = list(OrderedDict.fromkeys(lines))
    if len(unique_lines) != len(lines):
        logging.warning("Дублирующиеся строки в файле 'to.txt' были удалены.")
        lines = unique_lines

    # Обработка задач из файла to.txt
    for line in lines:
        line = line.partition("#")[0].strip()
        parts = line.split(" ")
        if len(parts) >= 2 and parts[1]:
            old_uid, new_uid = parts[0], parts[1]
            logging.info(f"Обработка задач для замены UID: {old_uid} -> {new_uid}")
            process_issues(source_client, target_client, old_uid, new_uid)

if __name__ == "__main__":
    main()