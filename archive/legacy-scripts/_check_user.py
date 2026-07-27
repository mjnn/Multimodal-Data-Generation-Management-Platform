from hmi.app_db import get_user_by_username, list_users

for u in list_users():
    print(u["username"], u.get("roles"), u.get("is_active"))

admin = get_user_by_username("admin")
print("admin_roles", admin.get("roles") if admin else None)
