import os

from django.core.files.uploadedfile import UploadedFile
from rest_framework import serializers

from apps.modules.contracts.models import Contract
from apps.modules.contracts.services import effective_contract_display
from apps.modules.serializers_guard import reject_client_pk_on_create
from apps.modules.vendors.models import Vendor

ALLOWED_CONTRACT_FILE_EXTENSIONS = {"pdf", "jpg", "jpeg", "png", "doc", "docx", "xls", "xlsx"}
MAX_CONTRACT_FILE_BYTES = 10 * 1024 * 1024


class ContractSerializer(serializers.ModelSerializer):
    display_status = serializers.SerializerMethodField(read_only=True)
    is_expired = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Contract
        fields = [
            "id",
            "tenant",
            "vendor",
            "contract_number",
            "date_from",
            "date_to",
            "contract_amount",
            "currency",
            "contract_status",
            "contract_terms",
            "contract_file",
            "acc_number",
            "display_status",
            "is_expired",
            "created_at",
            "created_by",
            "updated_at",
        ]
        read_only_fields = ["id", "tenant", "created_at", "created_by", "updated_at", "display_status", "is_expired"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        tenant = getattr(request, "tenant", None) if request else None
        if tenant is not None and "vendor" in self.fields:
            self.fields["vendor"].queryset = Vendor.objects.filter(tenant=tenant)

    def get_display_status(self, obj: Contract) -> str:
        return effective_contract_display(obj)[0]

    def get_is_expired(self, obj: Contract) -> bool:
        return effective_contract_display(obj)[1]

    def validate(self, attrs):
        reject_client_pk_on_create(self)
        request = self.context.get("request")
        tenant = getattr(request, "tenant", None) if request else None
        vendor = attrs.get("vendor")
        if vendor is None and self.instance is not None:
            vendor = self.instance.vendor
        number = (attrs.get("contract_number") if "contract_number" in attrs else None)
        if number is None and self.instance is not None:
            number = self.instance.contract_number
        number = str(number or "").strip()
        if not number:
            raise serializers.ValidationError({"contract_number": "Укажите номер договора."})
        attrs["contract_number"] = number

        date_from = attrs.get("date_from")
        if date_from is None and self.instance is not None:
            date_from = self.instance.date_from

        if tenant and vendor:
            if vendor.tenant_id != tenant.id:
                raise serializers.ValidationError({"vendor": "Поставщик не принадлежит этому тенанту."})
            qs = Contract.objects.filter(
                tenant=tenant, vendor=vendor, contract_number=number, date_from=date_from
            )
            if self.instance is not None:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    {"contract_number": "Договор с таким номером и датой начала уже есть у этого поставщика."}
                )

        uploaded = None
        if request and getattr(request, "FILES", None):
            uploaded = request.FILES.get("contract_file")
        if self.instance is None and not isinstance(uploaded, UploadedFile):
            raise serializers.ValidationError({"contract_file": "Прикрепите файл договора."})
        if uploaded is not None and isinstance(uploaded, UploadedFile):
            fn = os.path.basename(uploaded.name or "file") or "file"
            ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else ""
            if ext not in ALLOWED_CONTRACT_FILE_EXTENSIONS:
                raise serializers.ValidationError(
                    {
                        "contract_file": (
                            "Недопустимый тип файла. Допустимо: "
                            f"{', '.join(sorted(ALLOWED_CONTRACT_FILE_EXTENSIONS))}."
                        )
                    }
                )
            if int(getattr(uploaded, "size", 0) or 0) > MAX_CONTRACT_FILE_BYTES:
                raise serializers.ValidationError({"contract_file": "Файл слишком большой (макс. 10 МБ)."})
            attrs["contract_file"] = uploaded

        return attrs
