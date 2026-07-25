-- ============================================================================
-- DOES4U MASTER DATABASE SCHEMA - 7 MODULES
-- ============================================================================

-- 1. DOES4U_OPERATION (Command Center)
-- ============================================================================

CREATE TABLE IF NOT EXISTS does4u_operation_goals (
    id SERIAL PRIMARY KEY,
    goal_id VARCHAR(50) UNIQUE NOT NULL,
    title VARCHAR(255) NOT NULL,
    quarter VARCHAR(10), -- Q1, Q2, Q3, Q4
    status VARCHAR(50) DEFAULT 'pending', -- pending, in_progress, completed
    target_kpi DECIMAL(10, 2),
    current_progress DECIMAL(10, 2) DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS does4u_operation_weekly_tasks (
    id SERIAL PRIMARY KEY,
    task_id VARCHAR(50) UNIQUE NOT NULL,
    related_module VARCHAR(50), -- operation, blog, channel, assets, academy, crm, listings
    description TEXT NOT NULL,
    priority VARCHAR(20), -- high, medium, low
    status VARCHAR(50) DEFAULT 'pending', -- pending, in_progress, completed, blocked
    due_date DATE,
    assigned_to VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

-- 2. DOES4U_BLOG (Content Engine)
-- ============================================================================

CREATE TABLE IF NOT EXISTS does4u_blog_articles (
    id SERIAL PRIMARY KEY,
    article_id VARCHAR(50) UNIQUE NOT NULL,
    title VARCHAR(255) NOT NULL,
    topic VARCHAR(100),
    content TEXT,
    status VARCHAR(50) DEFAULT 'idea', -- idea, draft, published, archived
    url VARCHAR(500) UNIQUE,
    slug VARCHAR(255),
    meta_description TEXT,
    featured_image_url VARCHAR(500),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    published_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS does4u_blog_traffic (
    id SERIAL PRIMARY KEY,
    article_id INTEGER NOT NULL REFERENCES does4u_blog_articles(id),
    traffic_date DATE,
    visitors INTEGER DEFAULT 0,
    avg_session_duration DECIMAL(8, 2), -- σε δευτερόλεπτα
    traffic_source VARCHAR(50), -- organic, direct, social, referral
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. DOES4U_CHANNEL (Growth & Media)
-- ============================================================================

CREATE TABLE IF NOT EXISTS does4u_channel_media (
    id SERIAL PRIMARY KEY,
    video_id VARCHAR(50) UNIQUE NOT NULL,
    platform VARCHAR(50) NOT NULL, -- youtube, tiktok, instagram, linkedin
    title VARCHAR(255) NOT NULL,
    status VARCHAR(50) DEFAULT 'draft', -- draft, published, scheduled, archived
    draft_link VARCHAR(500),
    published_link VARCHAR(500),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    published_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS does4u_channel_performance (
    id SERIAL PRIMARY KEY,
    video_id INTEGER NOT NULL REFERENCES does4u_channel_media(id),
    performance_date DATE,
    views INTEGER DEFAULT 0,
    likes INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    shares INTEGER DEFAULT 0,
    subscribers_gain INTEGER DEFAULT 0,
    revenue_estimate DECIMAL(10, 2) DEFAULT 0,
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 4. DOES4U_ASSETS (R&D & Production)
-- ============================================================================

CREATE TABLE IF NOT EXISTS does4u_assets_library (
    id SERIAL PRIMARY KEY,
    asset_id VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    type VARCHAR(100), -- ai_agent, scraper, tool, template, script
    description TEXT,
    tags VARCHAR(500), -- comma-separated
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS does4u_assets_dev_cycle (
    id SERIAL PRIMARY KEY,
    asset_id INTEGER NOT NULL REFERENCES does4u_assets_library(id),
    status VARCHAR(50) DEFAULT 'concept', -- concept, in_dev, live, maintenance
    repo_link VARCHAR(500),
    documentation_link VARCHAR(500),
    last_updated TIMESTAMP,
    deployed_version VARCHAR(50),
    notes TEXT
);

-- 5. DOES4U_ACADEMY (Education Pipeline)
-- ============================================================================

CREATE TABLE IF NOT EXISTS does4u_academy_courses (
    id SERIAL PRIMARY KEY,
    course_id VARCHAR(50) UNIQUE NOT NULL,
    title VARCHAR(255) NOT NULL,
    level VARCHAR(50), -- beginner, intermediate, advanced
    target_audience VARCHAR(255),
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS does4u_academy_curriculum (
    id SERIAL PRIMARY KEY,
    module_id VARCHAR(50) UNIQUE NOT NULL,
    course_id INTEGER NOT NULL REFERENCES does4u_academy_courses(id),
    module_number INTEGER,
    title VARCHAR(255) NOT NULL,
    content_status VARCHAR(50) DEFAULT 'planned', -- planned, recording, editing, ready
    video_url VARCHAR(500),
    resources_url VARCHAR(500),
    duration_minutes INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS does4u_academy_progress (
    id SERIAL PRIMARY KEY,
    user_email VARCHAR(255) NOT NULL,
    course_id INTEGER NOT NULL REFERENCES does4u_academy_courses(id),
    modules_completed INTEGER DEFAULT 0,
    progress_percentage DECIMAL(5, 2) DEFAULT 0,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    UNIQUE(user_email, course_id)
);

-- 6. DOES4U_CRM (Revenue Hub)
-- ============================================================================

CREATE TABLE IF NOT EXISTS does4u_crm_clients (
    id SERIAL PRIMARY KEY,
    client_id VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    company VARCHAR(255),
    email VARCHAR(255) UNIQUE,
    phone VARCHAR(20),
    contact_method VARCHAR(50), -- email, whatsapp, linkedin, other
    status VARCHAR(50) DEFAULT 'lead', -- lead, prospect, client, archived
    source VARCHAR(100), -- does4u, referral, social, other
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_contact_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS does4u_crm_projects (
    id SERIAL PRIMARY KEY,
    project_id VARCHAR(50) UNIQUE NOT NULL,
    client_id INTEGER NOT NULL REFERENCES does4u_crm_clients(id),
    title VARCHAR(255) NOT NULL,
    description TEXT,
    stage VARCHAR(50) DEFAULT 'lead', -- lead, proposal, active, completed, lost
    value DECIMAL(12, 2),
    currency VARCHAR(10) DEFAULT 'EUR',
    next_step VARCHAR(500),
    next_step_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

-- 7. LISTINGS (Fiverr/Upwork/Freelancer)
-- ============================================================================

CREATE TABLE IF NOT EXISTS listings (
    id SERIAL PRIMARY KEY,
    listing_id VARCHAR(50) UNIQUE NOT NULL,
    platform VARCHAR(50) NOT NULL, -- fiverr, upwork, freelancer, other
    category VARCHAR(50), -- dev, scraping, design, content, other
    title TEXT NOT NULL,
    description TEXT,
    price DECIMAL(10, 2),
    currency VARCHAR(10) DEFAULT 'USD',
    url TEXT UNIQUE,
    status VARCHAR(50) DEFAULT 'active', -- active, paused, archived
    views INTEGER DEFAULT 0,
    orders INTEGER DEFAULT 0,
    rating DECIMAL(3, 1),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- INDEXES FOR PERFORMANCE
-- ============================================================================

-- Operation Indexes
CREATE INDEX IF NOT EXISTS idx_operation_goals_status ON does4u_operation_goals(status);
CREATE INDEX IF NOT EXISTS idx_operation_goals_quarter ON does4u_operation_goals(quarter);
CREATE INDEX IF NOT EXISTS idx_operation_tasks_status ON does4u_operation_weekly_tasks(status);
CREATE INDEX IF NOT EXISTS idx_operation_tasks_module ON does4u_operation_weekly_tasks(related_module);
CREATE INDEX IF NOT EXISTS idx_operation_tasks_due_date ON does4u_operation_weekly_tasks(due_date);

-- Blog Indexes
CREATE INDEX IF NOT EXISTS idx_blog_articles_status ON does4u_blog_articles(status);
CREATE INDEX IF NOT EXISTS idx_blog_articles_topic ON does4u_blog_articles(topic);
CREATE INDEX IF NOT EXISTS idx_blog_articles_published_at ON does4u_blog_articles(published_at);
CREATE INDEX IF NOT EXISTS idx_blog_traffic_date ON does4u_blog_traffic(traffic_date);
CREATE INDEX IF NOT EXISTS idx_blog_traffic_article ON does4u_blog_traffic(article_id);

-- Channel Indexes
CREATE INDEX IF NOT EXISTS idx_channel_media_platform ON does4u_channel_media(platform);
CREATE INDEX IF NOT EXISTS idx_channel_media_status ON does4u_channel_media(status);
CREATE INDEX IF NOT EXISTS idx_channel_perf_date ON does4u_channel_performance(performance_date);
CREATE INDEX IF NOT EXISTS idx_channel_perf_video ON does4u_channel_performance(video_id);

-- Assets Indexes
CREATE INDEX IF NOT EXISTS idx_assets_type ON does4u_assets_library(type);
CREATE INDEX IF NOT EXISTS idx_assets_dev_status ON does4u_assets_dev_cycle(status);

-- Academy Indexes
CREATE INDEX IF NOT EXISTS idx_academy_courses_level ON does4u_academy_courses(level);
CREATE INDEX IF NOT EXISTS idx_academy_curriculum_course ON does4u_academy_curriculum(course_id);
CREATE INDEX IF NOT EXISTS idx_academy_curriculum_status ON does4u_academy_curriculum(content_status);
CREATE INDEX IF NOT EXISTS idx_academy_progress_user ON does4u_academy_progress(user_email);
CREATE INDEX IF NOT EXISTS idx_academy_progress_course ON does4u_academy_progress(course_id);

-- CRM Indexes
CREATE INDEX IF NOT EXISTS idx_crm_clients_status ON does4u_crm_clients(status);
CREATE INDEX IF NOT EXISTS idx_crm_clients_email ON does4u_crm_clients(email);
CREATE INDEX IF NOT EXISTS idx_crm_projects_stage ON does4u_crm_projects(stage);
CREATE INDEX IF NOT EXISTS idx_crm_projects_client ON does4u_crm_projects(client_id);

-- Listings Indexes
CREATE INDEX IF NOT EXISTS idx_listings_platform ON listings(platform);
CREATE INDEX IF NOT EXISTS idx_listings_category ON listings(category);
CREATE INDEX IF NOT EXISTS idx_listings_status ON listings(status);