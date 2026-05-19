from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="OAuthClient",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("client_id", models.CharField(db_index=True, max_length=255, unique=True)),
                ("client_name", models.CharField(blank=True, max_length=255)),
                ("redirect_uris", models.JSONField(default=list)),
                ("grant_types", models.JSONField(default=list)),
                ("response_types", models.JSONField(default=list)),
                ("scope", models.CharField(blank=True, max_length=1000)),
                ("token_endpoint_auth_method", models.CharField(default="none", max_length=50)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "mcp_oauth_client"},
        ),
        migrations.CreateModel(
            name="OAuthAuthorizationCode",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(db_index=True, max_length=255, unique=True)),
                ("redirect_uri", models.TextField()),
                ("redirect_uri_provided_explicitly", models.BooleanField(default=False)),
                ("code_challenge", models.CharField(max_length=255)),
                ("code_challenge_method", models.CharField(default="S256", max_length=10)),
                ("scopes", models.JSONField(default=list)),
                ("state", models.CharField(blank=True, max_length=255)),
                ("expires_at", models.DateTimeField()),
                ("used", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("client", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="mcp_oauth.oauthclient")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="mcp_oauth_codes", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "mcp_oauth_authorization_code"},
        ),
        migrations.AddIndex(
            model_name="oauthauthorizationcode",
            index=models.Index(fields=["code", "used"], name="mcp_auth_code_idx"),
        ),
    ]
