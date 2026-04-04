from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False, default="")
    new_password = serializers.CharField(required=True, allow_blank=False, trim_whitespace=False)


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ser = ChangePasswordSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        old_password = ser.validated_data.get("old_password") or ""
        new_password = ser.validated_data["new_password"]
        user = request.user

        if user.has_usable_password():
            if not old_password.strip():
                return Response(
                    {"detail": "Укажите текущий пароль."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not user.check_password(old_password):
                return Response(
                    {"detail": "Неверный текущий пароль."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        try:
            validate_password(new_password, user=user)
        except DjangoValidationError as exc:
            return Response(
                {"detail": " ".join(exc.messages) if exc.messages else "Пароль не прошёл проверку."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(new_password)
        user.save(update_fields=["password"])
        return Response({"detail": "Пароль обновлён."}, status=status.HTTP_200_OK)
