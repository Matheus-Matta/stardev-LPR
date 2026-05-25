# Guia por Model

Cada model agora tem um guia proprio, seguindo o padrao:

```text
Caso de uso -> Diagrama de estado -> Modelos -> Exemplos -> JSON e API -> Webhook, quando existir
```

## Tenancy

- [Business](model_workflows/01_business.md)
- [Tenant](model_workflows/02_tenant.md)
- [UserProfile](model_workflows/03_user_profile.md)
- [UserTenantAccess](model_workflows/04_user_tenant_access.md)

## Cameras e Ingest

- [Camera](model_workflows/05_camera.md)
- [Gateway](model_workflows/06_gateway.md)

## Plates e Operacao

- [PlateEvent](model_workflows/07_plate_event.md)
- [PlateRegistry](model_workflows/08_plate_registry.md)
- [AccessEvent](model_workflows/09_access_event.md)
- [VehiclePresence](model_workflows/10_vehicle_presence.md)
- [Alert](model_workflows/11_alert.md)

## Common, Webhooks, MLOps e LGPD

- [DeadLetterTask](model_workflows/12_dead_letter_task.md)
- [AuditLog](model_workflows/13_audit_log.md)
- [WebhookSubscription](model_workflows/14_webhook_subscription.md)
- [WebhookDelivery](model_workflows/15_webhook_delivery.md)
- [AIModelArtifact](model_workflows/16_ai_model_artifact.md)
- [DataProcessingRecord](model_workflows/17_data_processing_record.md)
- [DataSubjectRequest](model_workflows/18_data_subject_request.md)
- [SecurityIncident](model_workflows/19_security_incident.md)
