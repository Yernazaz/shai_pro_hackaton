-- Extended synthetic dataset for September 2024 – September 2025
-- Populates additional employees, clients, appointments, services and payments

-- Additional employees
WITH new_employee_people AS (
    SELECT
        gs AS seq,
        CONCAT('Сотрудник', LPAD(gs::text, 3, '0')) AS first_name,
        CONCAT('Работник', LPAD(gs::text, 3, '0')) AS last_name,
        CONCAT('Демонстрационный', LPAD(gs::text, 3, '0')) AS middle_name,
        FORMAT('+7703%07s', gs) AS phone_number,
        FORMAT('employee%03s@beauty.kz', gs) AS email,
        (DATE '1980-01-01' + (gs * 35)) AS birth_date,
        CASE WHEN gs % 2 = 0 THEN 'female' ELSE 'male' END AS gender
    FROM generate_series(11, 40) AS gs
), employee_people AS (
    INSERT INTO crm_people (first_name, last_name, middle_name, phone_number, email, birth_date, gender)
    SELECT np.first_name, np.last_name, np.middle_name, np.phone_number, np.email, np.birth_date, np.gender
    FROM new_employee_people np
    ON CONFLICT (phone_number) DO NOTHING
    RETURNING id, phone_number
)
INSERT INTO crm_employees (person_id, position, hire_date, is_active)
SELECT p.id,
       CASE (np.seq % 8)
            WHEN 0 THEN 'Колорист'
            WHEN 1 THEN 'Стилист'
            WHEN 2 THEN 'Барбер'
            WHEN 3 THEN 'Косметолог'
            WHEN 4 THEN 'Массажист'
            WHEN 5 THEN 'Мастер маникюра'
            WHEN 6 THEN 'Лэшмейкер'
            ELSE 'SPA-терапевт'
       END AS position,
       (DATE '2018-01-01' + (np.seq * 20)) AS hire_date,
       TRUE
FROM new_employee_people np
JOIN crm_people p ON p.phone_number = np.phone_number
LEFT JOIN crm_employees e ON e.person_id = p.id
WHERE e.person_id IS NULL;

-- Additional clients
WITH new_client_people AS (
    SELECT
        gs AS seq,
        CONCAT('Клиент', LPAD(gs::text, 3, '0')) AS first_name,
        CONCAT('Демонстрация', LPAD(gs::text, 3, '0')) AS last_name,
        CONCAT('Примерович', LPAD(gs::text, 3, '0')) AS middle_name,
        FORMAT('+7705%07s', gs) AS phone_number,
        FORMAT('client%03s@mail.kz', gs) AS email,
        (DATE '1990-01-01' + (gs * 13)) AS birth_date,
        CASE gs % 3 WHEN 0 THEN 'female' WHEN 1 THEN 'male' ELSE 'female' END AS gender
    FROM generate_series(101, 300) AS gs
), client_people AS (
    INSERT INTO crm_people (first_name, last_name, middle_name, phone_number, email, birth_date, gender)
    SELECT np.first_name, np.last_name, np.middle_name, np.phone_number, np.email, np.birth_date, np.gender
    FROM new_client_people np
    ON CONFLICT (phone_number) DO NOTHING
    RETURNING id, phone_number
)
INSERT INTO crm_clients (person_id, loyalty_level, referred_by, notes)
SELECT p.id,
       CASE (np.seq % 4)
            WHEN 0 THEN 'standard'
            WHEN 1 THEN 'silver'
            WHEN 2 THEN 'gold'
            ELSE 'platinum'
       END AS loyalty_level,
       CASE (np.seq % 5)
            WHEN 0 THEN 'Instagram'
            WHEN 1 THEN 'Website'
            WHEN 2 THEN 'Friend'
            WHEN 3 THEN 'Billboard'
            ELSE 'Walk-in'
       END AS referred_by,
       CONCAT('Сгенерированный клиент #', LPAD(np.seq::text, 3, '0')) AS notes
FROM new_client_people np
JOIN crm_people p ON p.phone_number = np.phone_number
LEFT JOIN crm_clients c ON c.person_id = p.id
WHERE c.person_id IS NULL;

-- Map new employees to services
WITH new_emps AS (
    SELECT e.id, ROW_NUMBER() OVER (ORDER BY e.id) AS rn
    FROM crm_employees e
    JOIN crm_people p ON p.id = e.person_id
    WHERE p.first_name LIKE 'Сотрудник%'
), services_subset AS (
    SELECT s.id, s.name, s.base_price, s.duration_minutes, ROW_NUMBER() OVER (ORDER BY s.id) AS rn
    FROM crm_services s
), pairs AS (
    SELECT ne.id AS employee_id,
           ss.id AS service_id,
           CASE ((ne.rn + ss.rn) % 3)
                WHEN 0 THEN 'expert'
                WHEN 1 THEN 'master'
                ELSE 'intermediate'
           END AS expertise_level
    FROM new_emps ne
    JOIN services_subset ss ON ss.rn <= 8
)
INSERT INTO crm_employee_services (employee_id, service_id, expertise_level)
SELECT DISTINCT p.employee_id, p.service_id, p.expertise_level
FROM pairs p
ON CONFLICT DO NOTHING;

-- Generate appointments across Sep 2024 – Sep 2025
WITH clients_ordered AS (
    SELECT c.id, ROW_NUMBER() OVER (ORDER BY c.id) AS rn FROM crm_clients c
), employees_ordered AS (
    SELECT e.id, ROW_NUMBER() OVER (ORDER BY e.id) AS rn FROM crm_employees e
), services_ordered AS (
    SELECT s.id, s.base_price, s.duration_minutes, ROW_NUMBER() OVER (ORDER BY s.id) AS rn
    FROM crm_services s
), counts AS (
    SELECT (SELECT COUNT(*) FROM clients_ordered) AS client_cnt,
           (SELECT COUNT(*) FROM employees_ordered) AS emp_cnt,
           (SELECT COUNT(*) FROM services_ordered) AS svc_cnt
), slot_calendar AS (
    SELECT
        day::date AS day,
        slot_index,
        ROW_NUMBER() OVER (ORDER BY day, slot_index) AS slot_idx,
        (day::timestamp + (TIME '09:00' + (slot_index - 1) * INTERVAL '3 hour')) AS start_ts
    FROM generate_series('2024-09-01'::date, '2025-09-30'::date, INTERVAL '1 day') AS day
    CROSS JOIN generate_series(1,3) AS slot_index
), appointment_data AS (
    SELECT
        sc.slot_idx,
        sc.start_ts,
        sc.start_ts + make_interval(mins => (svc.duration_minutes + ((sc.slot_idx % 3) * 10))) AS end_ts,
        cli.id AS client_id,
        emp.id AS employee_id,
        svc.id AS service_id,
        svc.base_price,
        svc.duration_minutes + ((sc.slot_idx % 3) * 10) AS service_duration,
        CASE
            WHEN sc.slot_idx % 20 = 0 THEN 'cancelled'
            WHEN sc.slot_idx % 17 = 0 THEN 'no_show'
            WHEN sc.slot_idx % 11 = 0 THEN 'partial'
            ELSE 'completed'
        END AS status,
        CASE
            WHEN sc.slot_idx % 9 = 0 THEN 'Повторный визит'
            WHEN sc.slot_idx % 7 = 0 THEN 'Новый клиент'
            ELSE 'Автоматически сгенерировано'
        END AS notes
    FROM slot_calendar sc
    CROSS JOIN counts cnt
    JOIN clients_ordered cli ON cli.rn = ((sc.slot_idx - 1) % cnt.client_cnt) + 1
    JOIN employees_ordered emp ON emp.rn = ((sc.slot_idx * 3 - 1) % cnt.emp_cnt) + 1
    JOIN services_ordered svc ON svc.rn = ((sc.slot_idx * 5 - 1) % cnt.svc_cnt) + 1
), final_appointments AS (
    SELECT
        ad.slot_idx,
        ad.start_ts,
        ad.end_ts,
        ad.client_id,
        ad.employee_id,
        ad.service_id,
        ad.service_duration,
        CASE
            WHEN ad.status IN ('cancelled','no_show') THEN 0
            ELSE ad.base_price + ((ad.slot_idx % 4) * 500)
        END AS total_price,
        CASE ad.status
            WHEN 'completed' THEN ad.base_price + ((ad.slot_idx % 4) * 500)
            WHEN 'partial' THEN ROUND((ad.base_price + ((ad.slot_idx % 4) * 500)) * 0.6)
            ELSE 0
        END AS paid_amount,
        CASE ad.status
            WHEN 'completed' THEN 'paid'
            WHEN 'partial' THEN 'partial'
            ELSE 'unpaid'
        END AS payment_status,
        ad.status,
        ad.notes
    FROM appointment_data ad
)
INSERT INTO crm_appointments (client_id, primary_employee_id, scheduled_start, scheduled_end, status, total_price, paid_amount, payment_status, notes)
SELECT fa.client_id, fa.employee_id, fa.start_ts, fa.end_ts, fa.status, fa.total_price, fa.paid_amount, fa.payment_status, fa.notes
FROM final_appointments fa
WHERE NOT EXISTS (
    SELECT 1 FROM crm_appointments existing
    WHERE existing.client_id = fa.client_id AND existing.scheduled_start = fa.start_ts
);

WITH clients_ordered AS (
    SELECT c.id, ROW_NUMBER() OVER (ORDER BY c.id) AS rn FROM crm_clients c
), employees_ordered AS (
    SELECT e.id, ROW_NUMBER() OVER (ORDER BY e.id) AS rn FROM crm_employees e
), services_ordered AS (
    SELECT s.id, s.base_price, s.duration_minutes, ROW_NUMBER() OVER (ORDER BY s.id) AS rn
    FROM crm_services s
), counts AS (
    SELECT (SELECT COUNT(*) FROM clients_ordered) AS client_cnt,
           (SELECT COUNT(*) FROM employees_ordered) AS emp_cnt,
           (SELECT COUNT(*) FROM services_ordered) AS svc_cnt
), slot_calendar AS (
    SELECT
        day::date AS day,
        slot_index,
        ROW_NUMBER() OVER (ORDER BY day, slot_index) AS slot_idx,
        (day::timestamp + (TIME '09:00' + (slot_index - 1) * INTERVAL '3 hour')) AS start_ts
    FROM generate_series('2024-09-01'::date, '2025-09-30'::date, INTERVAL '1 day') AS day
    CROSS JOIN generate_series(1,3) AS slot_index
), appointment_data AS (
    SELECT
        sc.slot_idx,
        sc.start_ts,
        sc.start_ts + make_interval(mins => (svc.duration_minutes + ((sc.slot_idx % 3) * 10))) AS end_ts,
        cli.id AS client_id,
        emp.id AS employee_id,
        svc.id AS service_id,
        svc.base_price,
        svc.duration_minutes + ((sc.slot_idx % 3) * 10) AS service_duration,
        CASE
            WHEN sc.slot_idx % 20 = 0 THEN 'cancelled'
            WHEN sc.slot_idx % 17 = 0 THEN 'no_show'
            WHEN sc.slot_idx % 11 = 0 THEN 'partial'
            ELSE 'completed'
        END AS status
    FROM slot_calendar sc
    CROSS JOIN counts cnt
    JOIN clients_ordered cli ON cli.rn = ((sc.slot_idx - 1) % cnt.client_cnt) + 1
    JOIN employees_ordered emp ON emp.rn = ((sc.slot_idx * 3 - 1) % cnt.emp_cnt) + 1
    JOIN services_ordered svc ON svc.rn = ((sc.slot_idx * 5 - 1) % cnt.svc_cnt) + 1
), final_appointments AS (
    SELECT
        ad.slot_idx,
        ad.start_ts,
        ad.end_ts,
        ad.client_id,
        ad.employee_id,
        ad.service_id,
        ad.service_duration,
        CASE WHEN ad.status IN ('cancelled','no_show') THEN 0 ELSE ad.base_price + ((ad.slot_idx % 4) * 500) END AS total_price,
        ad.status
    FROM appointment_data ad
)
INSERT INTO crm_appointment_services (appointment_id, service_id, employee_id, price, duration_minutes, comment)
SELECT a.id,
       fa.service_id,
       fa.employee_id,
       CASE WHEN fa.status IN ('cancelled','no_show') THEN 0 ELSE fa.total_price END AS price,
       fa.service_duration,
       CASE fa.status
            WHEN 'completed' THEN 'Завершено успешно (генерация)'
            WHEN 'partial' THEN 'Частичная оплата (генерация)'
            WHEN 'no_show' THEN 'Клиент не явился'
            ELSE 'Визит отменён'
       END AS comment
FROM final_appointments fa
JOIN crm_appointments a ON a.client_id = fa.client_id AND a.scheduled_start = fa.start_ts
WHERE NOT EXISTS (
    SELECT 1 FROM crm_appointment_services cas
    WHERE cas.appointment_id = a.id AND cas.service_id = fa.service_id
);

-- Payments for generated appointments
WITH clients_ordered AS (
    SELECT c.id, ROW_NUMBER() OVER (ORDER BY c.id) AS rn FROM crm_clients c
), employees_ordered AS (
    SELECT e.id, ROW_NUMBER() OVER (ORDER BY e.id) AS rn FROM crm_employees e
), services_ordered AS (
    SELECT s.id, s.base_price, s.duration_minutes, ROW_NUMBER() OVER (ORDER BY s.id) AS rn
    FROM crm_services s
), counts AS (
    SELECT (SELECT COUNT(*) FROM clients_ordered) AS client_cnt,
           (SELECT COUNT(*) FROM employees_ordered) AS emp_cnt,
           (SELECT COUNT(*) FROM services_ordered) AS svc_cnt
), slot_calendar AS (
    SELECT
        day::date AS day,
        slot_index,
        ROW_NUMBER() OVER (ORDER BY day, slot_index) AS slot_idx,
        (day::timestamp + (TIME '09:00' + (slot_index - 1) * INTERVAL '3 hour')) AS start_ts
    FROM generate_series('2024-09-01'::date, '2025-09-30'::date, INTERVAL '1 day') AS day
    CROSS JOIN generate_series(1,3) AS slot_index
), appointment_data AS (
    SELECT
        sc.slot_idx,
        sc.start_ts,
        cli.id AS client_id,
        emp.id AS employee_id,
        svc.base_price,
        CASE
            WHEN sc.slot_idx % 20 = 0 THEN 'cancelled'
            WHEN sc.slot_idx % 17 = 0 THEN 'no_show'
            WHEN sc.slot_idx % 11 = 0 THEN 'partial'
            ELSE 'completed'
        END AS status
    FROM slot_calendar sc
    CROSS JOIN counts cnt
    JOIN clients_ordered cli ON cli.rn = ((sc.slot_idx - 1) % cnt.client_cnt) + 1
    JOIN employees_ordered emp ON emp.rn = ((sc.slot_idx * 3 - 1) % cnt.emp_cnt) + 1
    JOIN services_ordered svc ON svc.rn = ((sc.slot_idx * 5 - 1) % cnt.svc_cnt) + 1
), final_appointments AS (
    SELECT
        ad.slot_idx,
        ad.start_ts,
        ad.client_id,
        CASE WHEN ad.status IN ('cancelled','no_show') THEN 0 ELSE ad.base_price + ((ad.slot_idx % 4) * 500) END AS total_price,
        CASE ad.status
            WHEN 'completed' THEN ad.base_price + ((ad.slot_idx % 4) * 500)
            WHEN 'partial' THEN ROUND((ad.base_price + ((ad.slot_idx % 4) * 500)) * 0.6)
            ELSE 0
        END AS paid_amount,
        CASE ad.status
            WHEN 'completed' THEN 'paid'
            WHEN 'partial' THEN 'partial'
            ELSE 'unpaid'
        END AS payment_status
    FROM appointment_data ad
)
INSERT INTO crm_payments (appointment_id, amount, paid_at, method, reference)
SELECT a.id,
       fa.paid_amount,
       fa.start_ts + INTERVAL '2 hour' AS paid_at,
       CASE (fa.slot_idx % 3)
            WHEN 0 THEN 'card'
            WHEN 1 THEN 'cash'
            ELSE 'transfer'
       END AS method,
       FORMAT('INV-%s-%04s', TO_CHAR(fa.start_ts, 'YYYYMMDD'), fa.slot_idx) AS reference
FROM final_appointments fa
JOIN crm_appointments a ON a.client_id = fa.client_id AND a.scheduled_start = fa.start_ts
WHERE fa.paid_amount > 0
  AND NOT EXISTS (
        SELECT 1 FROM crm_payments p WHERE p.reference = FORMAT('INV-%s-%04s', TO_CHAR(fa.start_ts, 'YYYYMMDD'), fa.slot_idx)
    );
