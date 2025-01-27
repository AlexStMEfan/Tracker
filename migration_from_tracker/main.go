package main

import (
	"context"
	"encoding/csv"
	"errors"
	"fmt"
	"html/template"
	"log"
	"net/http"
	"os"
	"os/exec"
	"strings"
	"time"

	jira "github.com/andygrunwald/go-jira"
	"github.com/joho/godotenv"
	ycsdk "github.com/yandex-cloud/go-sdk"
	"github.com/yandex-cloud/go-sdk/iamkey"
	asana "github.com/toloko/go-asana/asana"
)

// Путь к файлу для маппинга пользователей
const userMappingFile = "user_mapping.csv"

// Шаблоны HTML
var (
	indexTemplate          = mustParseTemplate("templates/index.html")
	selectSourceTemplate   = mustParseTemplate("templates/select_source.html")
	selectJiraTemplate     = mustParseTemplate("templates/select_jira.html")
	selectAsanaTemplate    = mustParseTemplate("templates/select_asana.html")
	resultTemplate         = mustParseTemplate("templates/result.html")
	errorTemplate          = mustParseTemplate("templates/error.html")
)

// Загрузка HTML-шаблона
func mustParseTemplate(filePath string) *template.Template {
	tmpl, err := template.ParseFiles(filePath)
	if err != nil {
		log.Fatalf("Error loading template %s: %v", filePath, err)
	}
	return tmpl
}

// Отображение ошибки на веб-странице
func renderError(w http.ResponseWriter, message string, statusCode int) {
	w.WriteHeader(statusCode)
	err := errorTemplate.Execute(w, map[string]string{"Message": message})
	if err != nil {
		log.Printf("Error rendering error page: %v", err)
	}
}

// Главная страница
func homeHandler(w http.ResponseWriter, r *http.Request) {
	if err := indexTemplate.Execute(w, nil); err != nil {
		renderError(w, "Ошибка загрузки главной страницы.", http.StatusInternalServerError)
	}
}

// Обработка выбора источника данных (Jira или Asana)
func selectSourceHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method == http.MethodPost {
		source := r.FormValue("source")
		switch source {
		case "jira":
			http.Redirect(w, r, "/jira", http.StatusSeeOther)
		case "asana":
			http.Redirect(w, r, "/asana", http.StatusSeeOther)
		default:
			renderError(w, "Неверный источник данных.", http.StatusBadRequest)
		}
	} else {
		selectSourceTemplate.Execute(w, nil)
	}
}

// Функция для запуска скриптов Python
func runScriptWithArgs(scriptPath string, args ...string) (string, error) {
	cmd := exec.Command("python3", append([]string{scriptPath}, args...)...)
	output, err := cmd.CombinedOutput()
	if err != nil {
		return "", fmt.Errorf("error executing script: %v, output: %s", err, output)
	}
	return string(output), nil
}

// Инициализация клиента Jira
func InitJiraClient(jiraURL, jiraUser, jiraToken string) (*jira.Client, error) {
	tp := jira.BasicAuthTransport{
		Username: jiraUser,
		Password: jiraToken,
	}
	client, err := jira.NewClient(tp.Client(), jiraURL)
	if err != nil {
		return nil, fmt.Errorf("failed to initialize Jira client: %w", err)
	}
	log.Println("Jira client initialized successfully.")
	return client, nil
}

// Инициализация клиента Asana
func InitAsanaClient(accessToken string) (*asana.Client, error) {
	client := asana.NewClientWithAccessToken(accessToken)
	if client == nil {
		return nil, errors.New("failed to initialize Asana client")
	}
	log.Println("Asana client initialized successfully.")
	return client, nil
}

// Инициализация клиента Yandex Tracker
func InitTrackerClient(tokenPath, orgID, cloudOrgID string) (*ycsdk.SDK, error) {
	if orgID == "" && cloudOrgID == "" {
		return nil, fmt.Errorf("either ORG_ID or CLOUD_ORG_ID must be specified")
	}

	key, err := iamkey.ReadFromJSONFile(tokenPath)
	if err != nil {
		return nil, fmt.Errorf("failed to read Yandex IAM key: %w", err)
	}

	creds, err := ycsdk.ServiceAccountKey(key)
	if err != nil {
		return nil, fmt.Errorf("failed to create credentials from IAM key: %w", err)
	}

	sdk, err := ycsdk.Build(context.Background(), ycsdk.Config{
		Credentials: creds,
	})
	if err != nil {
		return nil, fmt.Errorf("failed to initialize Yandex Cloud SDK: %w", err)
	}

	log.Println("Yandex Tracker client initialized successfully.")
	return sdk, nil
}

// Загрузка маппинга пользователей из CSV
func ReadUserMapping(filePath string) (map[string]string, error) {
	file, err := os.Open(filePath)
	if err != nil {
		return nil, fmt.Errorf("failed to open user mapping file: %w", err)
	}
	defer file.Close()

	reader := csv.NewReader(file)
	records, err := reader.ReadAll()
	if err != nil {
		return nil, fmt.Errorf("failed to read user mapping file: %w", err)
	}

	userMapping := make(map[string]string)
	for _, record := range records[1:] { // Пропускаем заголовок
		if len(record) < 2 {
			continue
		}
		userMapping[record[0]] = record[1]
	}
	log.Println("User mapping loaded successfully.")
	return userMapping, nil
}

// Основная логика миграции данных
func MigrateDataFromJira(jiraClient *jira.Client, trackerClient *ycsdk.SDK, userMapping map[string]string) error {
	issues, _, err := jiraClient.Issue.Search("assignee IS NOT EMPTY", nil)
	if err != nil {
		return fmt.Errorf("failed to fetch issues from Jira: %w", err)
	}

	for _, issue := range issues {
		log.Printf("Processing issue: %s\n", issue.Key)
		assignee := userMapping[issue.Fields.Assignee.Name]
		log.Printf("Mapped Assignee: %s\n", assignee)
		// TODO: Реализовать логику создания задачи в Yandex Tracker
	}
	return nil
}

func main() {
	startTime := time.Now()
	log.Println("Starting migration tool...")

	// Загрузка переменных окружения
	if err := godotenv.Load(); err != nil {
		log.Fatalf("Error loading .env file: %v", err)
	}

	// Инициализация клиентов
	jiraURL := os.Getenv("JIRA_URL")
	jiraUser := os.Getenv("JIRA_USER")
	jiraAPIToken := os.Getenv("JIRA_API_TOKEN")
	tokenPath := os.Getenv("TOKEN_PATH")
	orgID := os.Getenv("ORG_ID")
	cloudOrgID := os.Getenv("CLOUD_ORG_ID")

	jiraClient, err := InitJiraClient(jiraURL, jiraUser, jiraAPIToken)
	if err != nil {
		log.Fatalf("Error initializing Jira client: %v", err)
	}

	trackerClient, err := InitTrackerClient(tokenPath, orgID, cloudOrgID)
	if err != nil {
		log.Fatalf("Error initializing Yandex Tracker client: %v", err)
	}

	userMapping, err := ReadUserMapping(userMappingFile)
	if err != nil {
		log.Fatalf("Error reading user mapping: %v", err)
	}

	err = MigrateDataFromJira(jiraClient, trackerClient, userMapping)
	if err != nil {
		log.Fatalf("Error during migration: %v", err)
	}

	http.HandleFunc("/", homeHandler)
	http.HandleFunc("/select", selectSourceHandler)

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}
	log.Printf("Server started at http://localhost:%s", port)
	if err := http.ListenAndServe(":"+port, nil); err != nil {
		log.Fatalf("Server failed: %v", err)
	}

	log.Printf("Migration completed in %v seconds.\n", time.Since(startTime).Seconds())
}
