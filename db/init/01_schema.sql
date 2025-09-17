BEGIN;

-- Base people table shared by clients and employees
CREATE TABLE IF NOT EXISTS crm_people (
    id SERIAL PRIMARY KEY,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    middle_name VARCHAR(100),
    phone_number VARCHAR(32) UNIQUE,
    email VARCHAR(254) UNIQUE,
    birth_date DATE,
    gender VARCHAR(16),
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Clients extend crm_people via one-to-one relationship
CREATE TABLE IF NOT EXISTS crm_clients (
    id SERIAL PRIMARY KEY,
    person_id INTEGER NOT NULL UNIQUE REFERENCES crm_people(id) ON DELETE CASCADE,
    loyalty_level VARCHAR(32),
    referred_by VARCHAR(128),
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    notes TEXT
);

-- Employees extend crm_people via one-to-one relationship
CREATE TABLE IF NOT EXISTS crm_employees (
    id SERIAL PRIMARY KEY,
    person_id INTEGER NOT NULL UNIQUE REFERENCES crm_people(id) ON DELETE CASCADE,
    position VARCHAR(120) NOT NULL,
    hire_date DATE NOT NULL,
    fire_date DATE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

-- Catalog of service categories (hair, nails, spa, etc.)
CREATE TABLE IF NOT EXISTS crm_service_categories (
    id SERIAL PRIMARY KEY,
    name VARCHAR(120) NOT NULL UNIQUE,
    description TEXT
);

-- Services offered to clients
CREATE TABLE IF NOT EXISTS crm_services (
    id SERIAL PRIMARY KEY,
    category_id INTEGER REFERENCES crm_service_categories(id) ON DELETE SET NULL,
    name VARCHAR(150) NOT NULL UNIQUE,
    base_price NUMERIC(12,2) NOT NULL,
    duration_minutes INTEGER NOT NULL,
    description TEXT
);

-- Mapping of employees to services they can perform
CREATE TABLE IF NOT EXISTS crm_employee_services (
    employee_id INTEGER NOT NULL REFERENCES crm_employees(id) ON DELETE CASCADE,
    service_id INTEGER NOT NULL REFERENCES crm_services(id) ON DELETE CASCADE,
    expertise_level VARCHAR(32),
    PRIMARY KEY (employee_id, service_id)
);

-- Appointments between clients and employees
CREATE TABLE IF NOT EXISTS crm_appointments (
    id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES crm_clients(id) ON DELETE CASCADE,
    primary_employee_id INTEGER REFERENCES crm_employees(id) ON DELETE SET NULL,
    scheduled_start TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    scheduled_end TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    status VARCHAR(20) NOT NULL CHECK (status IN ('scheduled','confirmed','completed','cancelled','no_show')),
    total_price NUMERIC(12,2) NOT NULL DEFAULT 0,
    paid_amount NUMERIC(12,2) NOT NULL DEFAULT 0,
    payment_status VARCHAR(20) NOT NULL DEFAULT 'unpaid' CHECK (payment_status IN ('unpaid','partial','paid','refunded')),
    notes TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    cancelled_at TIMESTAMP WITHOUT TIME ZONE
);

-- Service lines within an appointment
CREATE TABLE IF NOT EXISTS crm_appointment_services (
    id SERIAL PRIMARY KEY,
    appointment_id INTEGER NOT NULL REFERENCES crm_appointments(id) ON DELETE CASCADE,
    service_id INTEGER NOT NULL REFERENCES crm_services(id) ON DELETE CASCADE,
    employee_id INTEGER REFERENCES crm_employees(id) ON DELETE SET NULL,
    price NUMERIC(12,2) NOT NULL,
    duration_minutes INTEGER NOT NULL,
    comment TEXT
);

-- Payments captured for appointments
CREATE TABLE IF NOT EXISTS crm_payments (
    id SERIAL PRIMARY KEY,
    appointment_id INTEGER NOT NULL REFERENCES crm_appointments(id) ON DELETE CASCADE,
    amount NUMERIC(12,2) NOT NULL,
    paid_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    method VARCHAR(32) NOT NULL,
    reference VARCHAR(64)
);

-- Generic interactions for CRM-style tracking (calls, reminders)
CREATE TABLE IF NOT EXISTS crm_client_interactions (
    id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES crm_clients(id) ON DELETE CASCADE,
    interaction_type VARCHAR(32) NOT NULL,
    performed_by INTEGER REFERENCES crm_employees(id) ON DELETE SET NULL,
    occurred_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    notes TEXT
);

-- Helpful indexes
CREATE INDEX IF NOT EXISTS idx_clients_person ON crm_clients(person_id);
CREATE INDEX IF NOT EXISTS idx_employees_person ON crm_employees(person_id);
CREATE INDEX IF NOT EXISTS idx_appointments_client ON crm_appointments(client_id);
CREATE INDEX IF NOT EXISTS idx_appointments_employee ON crm_appointments(primary_employee_id);
CREATE INDEX IF NOT EXISTS idx_appointments_start ON crm_appointments(scheduled_start);
CREATE INDEX IF NOT EXISTS idx_appointment_services_appointment ON crm_appointment_services(appointment_id);
CREATE INDEX IF NOT EXISTS idx_appointment_services_employee ON crm_appointment_services(employee_id);
CREATE INDEX IF NOT EXISTS idx_payments_appointment ON crm_payments(appointment_id);
CREATE INDEX IF NOT EXISTS idx_client_interactions_client ON crm_client_interactions(client_id);

COMMIT;
