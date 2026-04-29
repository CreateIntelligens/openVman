## ADDED Requirements

### Requirement: Prometheus and Grafana run as compose services
The system SHALL include `prometheus` and `grafana` services in `docker-compose.yml` with persistent storage volumes, so metrics survive service restarts.

#### Scenario: Metrics persist after backend restart
- **WHEN** backend service restarts
- **THEN** Prometheus retains all previously scraped metric history
- **THEN** Grafana dashboard continues to display historical data

#### Scenario: Grafana datasource auto-provisioned
- **WHEN** grafana container starts for the first time
- **THEN** Prometheus datasource is available without manual UI configuration

### Requirement: Admin frontend embeds Grafana dashboard
Admin frontend SHALL include a monitoring page that embeds Grafana via iframe, accessible through the existing admin UI navigation.

#### Scenario: Monitoring page loads
- **WHEN** user navigates to the monitoring section in admin UI
- **THEN** a Grafana dashboard is displayed embedded within the admin page

#### Scenario: Grafana served under sub-path
- **WHEN** nginx proxies requests to `/grafana/`
- **THEN** Grafana UI loads correctly with all assets resolving under the sub-path
