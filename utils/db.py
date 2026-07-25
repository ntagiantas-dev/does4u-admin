"""
CRUD Functions για Does4U - 7 Modules
Operation, Blog, Channel, Assets, Academy, CRM, Listings
"""

import sys
import os
from pathlib import Path
import json
from datetime import datetime, date

# Import config
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import execute_query

# ============================================================================
# 1. DOES4U_OPERATION - GOALS & TASKS
# ============================================================================

def save_operation_goal(goal_id, title, quarter, target_kpi):
    """Αποθήκευση νέου quarterly goal."""
    query = """
    INSERT INTO does4u_operation_goals (goal_id, title, quarter, target_kpi, status)
    VALUES (%s, %s, %s, %s, 'pending')
    RETURNING id;
    """
    params = (goal_id, title, quarter, target_kpi)
    result = execute_query(query, params, fetch=True)
    return result[0][0] if result else None

def get_operation_goals(quarter=None, status=None):
    """Ανάκτηση goals (φίλτρο κατά quarter/status)."""
    if quarter and status:
        query = """
        SELECT id, goal_id, title, quarter, status, target_kpi, current_progress
        FROM does4u_operation_goals
        WHERE quarter = %s AND status = %s
        ORDER BY created_at DESC;
        """
        params = (quarter, status)
    elif quarter:
        query = """
        SELECT id, goal_id, title, quarter, status, target_kpi, current_progress
        FROM does4u_operation_goals
        WHERE quarter = %s
        ORDER BY created_at DESC;
        """
        params = (quarter,)
    else:
        query = """
        SELECT id, goal_id, title, quarter, status, target_kpi, current_progress
        FROM does4u_operation_goals
        ORDER BY created_at DESC;
        """
        params = None
    
    return execute_query(query, params, fetch=True)

def update_goal_progress(goal_id, progress):
    """Ενημέρωση progress ενός goal."""
    query = """
    UPDATE does4u_operation_goals
    SET current_progress = %s, updated_at = CURRENT_TIMESTAMP
    WHERE goal_id = %s
    RETURNING id;
    """
    params = (progress, goal_id)
    result = execute_query(query, params, fetch=True)
    return result[0][0] if result else None

def save_weekly_task(task_id, related_module, description, priority, due_date):
    """Αποθήκευση εβδομαδιαίου task."""
    query = """
    INSERT INTO does4u_operation_weekly_tasks 
    (task_id, related_module, description, priority, status, due_date)
    VALUES (%s, %s, %s, %s, 'pending', %s)
    RETURNING id;
    """
    params = (task_id, related_module, description, priority, due_date)
    result = execute_query(query, params, fetch=True)
    return result[0][0] if result else None

def get_weekly_tasks(status=None, module=None):
    """Ανάκτηση weekly tasks."""
    if status and module:
        query = """
        SELECT id, task_id, related_module, description, priority, status, due_date
        FROM does4u_operation_weekly_tasks
        WHERE status = %s AND related_module = %s
        ORDER BY due_date ASC;
        """
        params = (status, module)
    elif status:
        query = """
        SELECT id, task_id, related_module, description, priority, status, due_date
        FROM does4u_operation_weekly_tasks
        WHERE status = %s
        ORDER BY due_date ASC;
        """
        params = (status,)
    else:
        query = """
        SELECT id, task_id, related_module, description, priority, status, due_date
        FROM does4u_operation_weekly_tasks
        ORDER BY due_date ASC;
        """
        params = None
    
    return execute_query(query, params, fetch=True)

def update_task_status(task_id, new_status):
    """Ενημέρωση status ενός task."""
    completed_at = datetime.now() if new_status == 'completed' else None
    query = """
    UPDATE does4u_operation_weekly_tasks
    SET status = %s, completed_at = %s
    WHERE task_id = %s
    RETURNING id;
    """
    params = (new_status, completed_at, task_id)
    result = execute_query(query, params, fetch=True)
    return result[0][0] if result else None

# ============================================================================
# 2. DOES4U_BLOG - ARTICLES & TRAFFIC
# ============================================================================

def save_blog_article(article_id, title, topic, slug=None):
    """Αποθήκευση νέου blog article."""
    if not slug:
        slug = title.lower().replace(" ", "-")[:100]
    
    query = """
    INSERT INTO does4u_blog_articles 
    (article_id, title, topic, slug, status)
    VALUES (%s, %s, %s, %s, 'idea')
    RETURNING id;
    """
    params = (article_id, title, topic, slug)
    result = execute_query(query, params, fetch=True)
    return result[0][0] if result else None

def update_blog_article(article_id, title=None, content=None, status=None, featured_image_url=None):
    """Ενημέρωση blog article."""
    updates = ["updated_at = CURRENT_TIMESTAMP"]
    params = []
    
    if title:
        updates.append("title = %s")
        params.append(title)
    if content:
        updates.append("content = %s")
        params.append(content)
    if status:
        updates.append("status = %s")
        params.append(status)
        if status == 'published':
            updates.append("published_at = CURRENT_TIMESTAMP")
    if featured_image_url:
        updates.append("featured_image_url = %s")
        params.append(featured_image_url)
    
    params.append(article_id)
    
    query = f"""
    UPDATE does4u_blog_articles
    SET {', '.join(updates)}
    WHERE article_id = %s
    RETURNING id;
    """
    
    result = execute_query(query, tuple(params), fetch=True)
    return result[0][0] if result else None

def get_blog_articles(status=None, topic=None, limit=20):
    """Ανάκτηση blog articles."""
    if status and topic:
        query = """
        SELECT id, article_id, title, topic, status, slug, created_at, published_at
        FROM does4u_blog_articles
        WHERE status = %s AND topic = %s
        ORDER BY published_at DESC NULLS LAST
        LIMIT %s;
        """
        params = (status, topic, limit)
    elif status:
        query = """
        SELECT id, article_id, title, topic, status, slug, created_at, published_at
        FROM does4u_blog_articles
        WHERE status = %s
        ORDER BY published_at DESC NULLS LAST
        LIMIT %s;
        """
        params = (status, limit)
    else:
        query = """
        SELECT id, article_id, title, topic, status, slug, created_at, published_at
        FROM does4u_blog_articles
        ORDER BY published_at DESC NULLS LAST
        LIMIT %s;
        """
        params = (limit,)
    
    return execute_query(query, params, fetch=True)

def save_blog_traffic(article_id, traffic_date, visitors, avg_session_duration, traffic_source):
    """Αποθήκευση traffic metrics."""
    query = """
    INSERT INTO does4u_blog_traffic 
    (article_id, traffic_date, visitors, avg_session_duration, traffic_source)
    VALUES (%s, %s, %s, %s, %s)
    RETURNING id;
    """
    params = (article_id, traffic_date, visitors, avg_session_duration, traffic_source)
    result = execute_query(query, params, fetch=True)
    return result[0][0] if result else None

def get_blog_traffic(article_id=None, days=30):
    """Ανάκτηση traffic data."""
    if article_id:
        query = """
        SELECT id, article_id, traffic_date, visitors, avg_session_duration, traffic_source
        FROM does4u_blog_traffic
        WHERE article_id = %s AND traffic_date >= CURRENT_DATE - INTERVAL '%s days'
        ORDER BY traffic_date DESC;
        """
        params = (article_id, days)
    else:
        query = """
        SELECT id, article_id, traffic_date, visitors, avg_session_duration, traffic_source
        FROM does4u_blog_traffic
        WHERE traffic_date >= CURRENT_DATE - INTERVAL '%s days'
        ORDER BY traffic_date DESC;
        """
        params = (days,)
    
    return execute_query(query, params, fetch=True)

# ============================================================================
# 3. DOES4U_CHANNEL - MEDIA & PERFORMANCE
# ============================================================================

def save_channel_media(video_id, platform, title, status='draft'):
    """Αποθήκευση νέου channel item."""
    query = """
    INSERT INTO does4u_channel_media (video_id, platform, title, status)
    VALUES (%s, %s, %s, %s)
    RETURNING id;
    """
    params = (video_id, platform, title, status)
    result = execute_query(query, params, fetch=True)
    return result[0][0] if result else None

def update_channel_media(video_id, title=None, status=None, draft_link=None, published_link=None):
    """Ενημέρωση channel media."""
    updates = []
    params = []
    
    if title:
        updates.append("title = %s")
        params.append(title)
    if status:
        updates.append("status = %s")
        params.append(status)
        if status == 'published':
            updates.append("published_at = CURRENT_TIMESTAMP")
    if draft_link:
        updates.append("draft_link = %s")
        params.append(draft_link)
    if published_link:
        updates.append("published_link = %s")
        params.append(published_link)
    
    if not updates:
        return None
    
    params.append(video_id)
    
    query = f"""
    UPDATE does4u_channel_media
    SET {', '.join(updates)}
    WHERE video_id = %s
    RETURNING id;
    """
    
    result = execute_query(query, tuple(params), fetch=True)
    return result[0][0] if result else None

def get_channel_media(platform=None, status=None):
    """Ανάκτηση channel media."""
    if platform and status:
        query = """
        SELECT id, video_id, platform, title, status, draft_link, published_link
        FROM does4u_channel_media
        WHERE platform = %s AND status = %s
        ORDER BY created_at DESC;
        """
        params = (platform, status)
    elif platform:
        query = """
        SELECT id, video_id, platform, title, status, draft_link, published_link
        FROM does4u_channel_media
        WHERE platform = %s
        ORDER BY created_at DESC;
        """
        params = (platform,)
    else:
        query = """
        SELECT id, video_id, platform, title, status, draft_link, published_link
        FROM does4u_channel_media
        ORDER BY created_at DESC;
        """
        params = None
    
    return execute_query(query, params, fetch=True)

def save_channel_performance(video_id, perf_date, views=0, likes=0, comments=0, subscribers_gain=0, revenue=0):
    """Αποθήκευση performance metrics."""
    query = """
    INSERT INTO does4u_channel_performance 
    (video_id, performance_date, views, likes, comments, subscribers_gain, revenue_estimate)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    RETURNING id;
    """
    params = (video_id, perf_date, views, likes, comments, subscribers_gain, revenue)
    result = execute_query(query, params, fetch=True)
    return result[0][0] if result else None

def get_channel_performance(video_id=None, days=30):
    """Ανάκτηση performance data."""
    if video_id:
        query = """
        SELECT id, video_id, performance_date, views, likes, comments, subscribers_gain, revenue_estimate
        FROM does4u_channel_performance
        WHERE video_id = %s AND performance_date >= CURRENT_DATE - INTERVAL '%s days'
        ORDER BY performance_date DESC;
        """
        params = (video_id, days)
    else:
        query = """
        SELECT id, video_id, performance_date, views, likes, comments, subscribers_gain, revenue_estimate
        FROM does4u_channel_performance
        WHERE performance_date >= CURRENT_DATE - INTERVAL '%s days'
        ORDER BY performance_date DESC;
        """
        params = (days,)
    
    return execute_query(query, params, fetch=True)

# ============================================================================
# 4. DOES4U_ASSETS - LIBRARY & DEV CYCLE
# ============================================================================

def save_asset(asset_id, name, asset_type, description=None, tags=None):
    """Αποθήκευση νέου asset."""
    query = """
    INSERT INTO does4u_assets_library (asset_id, name, type, description, tags)
    VALUES (%s, %s, %s, %s, %s)
    RETURNING id;
    """
    params = (asset_id, name, asset_type, description, tags)
    result = execute_query(query, params, fetch=True)
    return result[0][0] if result else None

def get_assets(asset_type=None):
    """Ανάκτηση assets."""
    if asset_type:
        query = """
        SELECT id, asset_id, name, type, description, tags, created_at
        FROM does4u_assets_library
        WHERE type = %s
        ORDER BY created_at DESC;
        """
        params = (asset_type,)
    else:
        query = """
        SELECT id, asset_id, name, type, description, tags, created_at
        FROM does4u_assets_library
        ORDER BY created_at DESC;
        """
        params = None
    
    return execute_query(query, params, fetch=True)

def save_asset_dev_cycle(asset_id, status='concept', repo_link=None, deployed_version=None):
    """Αποθήκευση development cycle."""
    query = """
    INSERT INTO does4u_assets_dev_cycle (asset_id, status, repo_link, deployed_version)
    VALUES (%s, %s, %s, %s)
    RETURNING id;
    """
    params = (asset_id, status, repo_link, deployed_version)
    result = execute_query(query, params, fetch=True)
    return result[0][0] if result else None

def update_asset_dev_cycle(asset_id, status=None, repo_link=None, deployed_version=None):
    """Ενημέρωση dev cycle."""
    updates = ["last_updated = CURRENT_TIMESTAMP"]
    params = []
    
    if status:
        updates.append("status = %s")
        params.append(status)
    if repo_link:
        updates.append("repo_link = %s")
        params.append(repo_link)
    if deployed_version:
        updates.append("deployed_version = %s")
        params.append(deployed_version)
    
    params.append(asset_id)
    
    query = f"""
    UPDATE does4u_assets_dev_cycle
    SET {', '.join(updates)}
    WHERE asset_id = %s
    RETURNING id;
    """
    
    result = execute_query(query, tuple(params), fetch=True)
    return result[0][0] if result else None

def get_asset_dev_cycle(status=None):
    """Ανάκτηση dev cycle."""
    if status:
        query = """
        SELECT id, asset_id, status, repo_link, deployed_version, last_updated
        FROM does4u_assets_dev_cycle
        WHERE status = %s
        ORDER BY last_updated DESC;
        """
        params = (status,)
    else:
        query = """
        SELECT id, asset_id, status, repo_link, deployed_version, last_updated
        FROM does4u_assets_dev_cycle
        ORDER BY last_updated DESC;
        """
        params = None
    
    return execute_query(query, params, fetch=True)

# ============================================================================
# 5. DOES4U_ACADEMY - COURSES, CURRICULUM, PROGRESS
# ============================================================================

def save_academy_course(course_id, title, level, target_audience=None):
    """Αποθήκευση νέου course."""
    query = """
    INSERT INTO does4u_academy_courses (course_id, title, level, target_audience)
    VALUES (%s, %s, %s, %s)
    RETURNING id;
    """
    params = (course_id, title, level, target_audience)
    result = execute_query(query, params, fetch=True)
    return result[0][0] if result else None

def get_academy_courses(level=None):
    """Ανάκτηση courses."""
    if level:
        query = """
        SELECT id, course_id, title, level, target_audience, created_at
        FROM does4u_academy_courses
        WHERE level = %s
        ORDER BY created_at DESC;
        """
        params = (level,)
    else:
        query = """
        SELECT id, course_id, title, level, target_audience, created_at
        FROM does4u_academy_courses
        ORDER BY created_at DESC;
        """
        params = None
    
    return execute_query(query, params, fetch=True)

def save_curriculum_module(module_id, course_id, module_number, title, content_status='planned'):
    """Αποθήκευση curriculum module."""
    query = """
    INSERT INTO does4u_academy_curriculum 
    (module_id, course_id, module_number, title, content_status)
    VALUES (%s, %s, %s, %s, %s)
    RETURNING id;
    """
    params = (module_id, course_id, module_number, title, content_status)
    result = execute_query(query, params, fetch=True)
    return result[0][0] if result else None

def get_curriculum_modules(course_id):
    """Ανάκτηση modules ενός course."""
    query = """
    SELECT id, module_id, module_number, title, content_status, video_url, duration_minutes
    FROM does4u_academy_curriculum
    WHERE course_id = %s
    ORDER BY module_number ASC;
    """
    params = (course_id,)
    return execute_query(query, params, fetch=True)

def save_academy_progress(user_email, course_id):
    """Αποθήκευση user progress."""
    query = """
    INSERT INTO does4u_academy_progress (user_email, course_id)
    VALUES (%s, %s)
    ON CONFLICT (user_email, course_id) DO UPDATE
    SET started_at = CURRENT_TIMESTAMP
    RETURNING id;
    """
    params = (user_email, course_id)
    result = execute_query(query, params, fetch=True)
    return result[0][0] if result else None

def update_academy_progress(user_email, course_id, modules_completed):
    """Ενημέρωση user progress."""
    query = """
    UPDATE does4u_academy_progress
    SET modules_completed = %s,
        progress_percentage = (modules_completed::DECIMAL / 
            (SELECT COUNT(*) FROM does4u_academy_curriculum WHERE course_id = %s)) * 100
    WHERE user_email = %s AND course_id = %s
    RETURNING id;
    """
    params = (modules_completed, course_id, user_email, course_id)
    result = execute_query(query, params, fetch=True)
    return result[0][0] if result else None

# ============================================================================
# 6. DOES4U_CRM - CLIENTS & PROJECTS
# ============================================================================

def save_crm_client(client_id, name, company=None, email=None, contact_method='email', source='does4u'):
    """Αποθήκευση νέου client."""
    query = """
    INSERT INTO does4u_crm_clients 
    (client_id, name, company, email, contact_method, source, status)
    VALUES (%s, %s, %s, %s, %s, %s, 'lead')
    RETURNING id;
    """
    params = (client_id, name, company, email, contact_method, source)
    result = execute_query(query, params, fetch=True)
    return result[0][0] if result else None

def get_crm_clients(status=None):
    """Ανάκτηση clients."""
    if status:
        query = """
        SELECT id, client_id, name, company, email, status, created_at
        FROM does4u_crm_clients
        WHERE status = %s
        ORDER BY created_at DESC;
        """
        params = (status,)
    else:
        query = """
        SELECT id, client_id, name, company, email, status, created_at
        FROM does4u_crm_clients
        ORDER BY created_at DESC;
        """
        params = None
    
    return execute_query(query, params, fetch=True)

def save_crm_project(project_id, client_id, title, stage='lead', value=None):
    """Αποθήκευση νέου project."""
    query = """
    INSERT INTO does4u_crm_projects (project_id, client_id, title, stage, value)
    VALUES (%s, %s, %s, %s, %s)
    RETURNING id;
    """
    params = (project_id, client_id, title, stage, value)
    result = execute_query(query, params, fetch=True)
    return result[0][0] if result else None

def get_crm_projects(stage=None, client_id=None):
    """Ανάκτηση projects."""
    if stage and client_id:
        query = """
        SELECT id, project_id, client_id, title, stage, value, next_step, created_at
        FROM does4u_crm_projects
        WHERE stage = %s AND client_id = %s
        ORDER BY created_at DESC;
        """
        params = (stage, client_id)
    elif stage:
        query = """
        SELECT id, project_id, client_id, title, stage, value, next_step, created_at
        FROM does4u_crm_projects
        WHERE stage = %s
        ORDER BY created_at DESC;
        """
        params = (stage,)
    else:
        query = """
        SELECT id, project_id, client_id, title, stage, value, next_step, created_at
        FROM does4u_crm_projects
        ORDER BY created_at DESC;
        """
        params = None
    
    return execute_query(query, params, fetch=True)

def update_crm_project(project_id, stage=None, next_step=None, next_step_date=None):
    """Ενημέρωση project."""
    updates = []
    params = []
    
    if stage:
        updates.append("stage = %s")
        params.append(stage)
        if stage == 'completed':
            updates.append("completed_at = CURRENT_TIMESTAMP")
    if next_step:
        updates.append("next_step = %s")
        params.append(next_step)
    if next_step_date:
        updates.append("next_step_date = %s")
        params.append(next_step_date)
    
    if not updates:
        return None
    
    params.append(project_id)
    
    query = f"""
    UPDATE does4u_crm_projects
    SET {', '.join(updates)}
    WHERE project_id = %s
    RETURNING id;
    """
    
    result = execute_query(query, tuple(params), fetch=True)
    return result[0][0] if result else None

# ============================================================================
# 7. LISTINGS - Fiverr/Upwork/Freelancer
# ============================================================================

def save_listing(listing_id, platform, category, title, price, url):
    """Αποθήκευση νέου listing."""
    query = """
    INSERT INTO listings (listing_id, platform, category, title, price, url, status)
    VALUES (%s, %s, %s, %s, %s, %s, 'active')
    RETURNING id;
    """
    params = (listing_id, platform, category, title, price, url)
    result = execute_query(query, params, fetch=True)
    return result[0][0] if result else None

def get_listings(platform=None, category=None, status='active'):
    """Ανάκτηση listings."""
    if platform and category:
        query = """
        SELECT id, listing_id, platform, category, title, price, url, status, views, orders, rating
        FROM listings
        WHERE platform = %s AND category = %s AND status = %s
        ORDER BY created_at DESC;
        """
        params = (platform, category, status)
    elif platform:
        query = """
        SELECT id, listing_id, platform, category, title, price, url, status, views, orders, rating
        FROM listings
        WHERE platform = %s AND status = %s
        ORDER BY created_at DESC;
        """
        params = (platform, status)
    else:
        query = """
        SELECT id, listing_id, platform, category, title, price, url, status, views, orders, rating
        FROM listings
        WHERE status = %s
        ORDER BY created_at DESC;
        """
        params = (status,)
    
    return execute_query(query, params, fetch=True)

def update_listing(listing_id, views=None, orders=None, rating=None, status=None):
    """Ενημέρωση listing metrics."""
    updates = ["updated_at = CURRENT_TIMESTAMP"]
    params = []
    
    if views is not None:
        updates.append("views = %s")
        params.append(views)
    if orders is not None:
        updates.append("orders = %s")
        params.append(orders)
    if rating is not None:
        updates.append("rating = %s")
        params.append(rating)
    if status:
        updates.append("status = %s")
        params.append(status)
    
    params.append(listing_id)
    
    query = f"""
    UPDATE listings
    SET {', '.join(updates)}
    WHERE listing_id = %s
    RETURNING id;
    """
    
    result = execute_query(query, tuple(params), fetch=True)
    return result[0][0] if result else None

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_dashboard_overview():
    """Ανάκτηση overview data για το dashboard."""
    overview = {}
    
    # Total articles
    articles = execute_query("SELECT COUNT(*) FROM does4u_blog_articles WHERE status = 'published';", fetch=True)
    overview['total_articles'] = articles[0][0] if articles else 0
    
    # Total videos
    videos = execute_query("SELECT COUNT(*) FROM does4u_channel_media WHERE status = 'published';", fetch=True)
    overview['total_videos'] = videos[0][0] if videos else 0
    
    # Total clients
    clients = execute_query("SELECT COUNT(*) FROM does4u_crm_clients WHERE status IN ('client', 'prospect');", fetch=True)
    overview['total_clients'] = clients[0][0] if clients else 0
    
    # Active listings
    listings = execute_query("SELECT COUNT(*) FROM listings WHERE status = 'active';", fetch=True)
    overview['active_listings'] = listings[0][0] if listings else 0
    
    # Active courses
    courses = execute_query("SELECT COUNT(*) FROM does4u_academy_courses;", fetch=True)
    overview['active_courses'] = courses[0][0] if courses else 0
    
    # Active assets
    assets = execute_query("SELECT COUNT(*) FROM does4u_assets_library;", fetch=True)
    overview['active_assets'] = assets[0][0] if assets else 0
    
    return overview