ction.proposal_hash,
                        detail="automatic",
                    )
                )
            record_audit(
                session,
                action="operation_action.automated_proposal_ready",
                actor_type="system",
                actor_id="operations-automation",
                tenant_id=task.tenant_id,
                resource_type="operation_action",
                resource_id=str(action.id),
                metadata={"proposal_hash": digest},
            )
            generated += 1
        session.commit()
        return generated
    finally:
        session.close()


def run_queued_actions_once() -> int:
    session = get_session_factory()()
    done = 0
    try:
        # PostgreSQL singleton guard; sqlite test databases simply run one process.
        if (
            session.bind
            and session.bind.dialect.name == "postgresql"
            and not session.execute(text("SELECT pg_try_advisory_xact_lock(810005)")).scalar()
        ):
            return 0
        action_ids = [
            row[0]
            for row in session.query(OperationAction.id)
            .filter_by(status="queued")
            .filter(
                or_(
                    OperationAction.workflow_key.is_(None),
                    OperationAction.workflow_key != "finance.prepare_collection_followup",
                )
            )
            .limit(20)
            .all()
        ]
        for action_id in action_ids:
            action = session.get(OperationAction, action_id)
            if action is None:
                continue
            if (
                action.workflow_key == "finance.prepare_collection_followup"
                or (task := session.query(OperationTask).filter_by(
                    id=action.task_id, tenant_id=action.tenant_id
                ).one_or_none()) is not None
                and task.source_type == "agent_workbench"
            ):
                continue
            task = (
                session.query(OperationTask)
                .filter_by(id=action.task_id, tenant_id=action.tenant_id)
                .one_or_none()
            )
            if task is None or task.source_connection_id is None or task.source_record_id is None:
                _fail_action(session, action, "source_validation_failed")
                continue
            # Connection is always locked before the action. Connection PATCH uses
            # the same ordering, so a company-scope change cannot race execution.
            conn = (
                session.query(Connection)
                .filter_by(id=task.source_connection_id, tenant_id=action.tenant_id)
                .with_for_update()
                .one_or_none()
            )
            task = (
                session.query(OperationTask)
                .filter_by(id=action.task_id, tenant_id=action.tenant_id)
                .populate_existing()
                .with_for_update()
                .one_or_none()
            )
            action = (
                session.query(OperationAction)
                .filter_by(id=action_id, status="queued")
                .populate_existing()
                .with_for_update()
                .one_or_none()
            )
            if action is None:
                continue
            if (
                task is None
                or conn is None
                or task.source_connection_id != conn.id
                or task.source_record_id is None
            ):
                _fail_action(session, action, "source_validation_failed")
                continue
            # Older queued records predate workflow metadata.  They are treated
            # as the fixed invoice workflow but have no historical version to
            # compare, preserving approved work while still honoring a disable.
            workflow_key = action.workflow_key or "finance.overdue_invoice_followup"
            try:
                config = effective_config(session, action.tenant_id, workflow_key)
            except ValueError:
                _fail_action(session, action, "workflow_config_invalid")
                continue
            if not config["enabled"] or (
                action.workflow_config_version is not None
                and action.workflow_config_version != config["version"]
            ):
                _fail_action(session, action, "workflow_config_changed")
                continue
            if (
                not conn.is_active
                or conn.last_test_status != "success"
                or conn.selected_transport not in ("xmlrpc", "json2")
            ):
                _fail_action(session, action, "connection_unavailable")
                continue
            try:
                proposal = InvoiceActivityProposal.model_validate_json(action.proposal_json)
                _, digest = canonical_proposal(proposal)
                snapshot = json.loads(task.source_snapshot_json or "")
                if not isinstance(snapshot, dict):
                    _fail_action(session, action, "proposal_validation_failed")
                    continue
                snapshot_company_id = snapshot.get("company_id")
                if (
                    digest != action.proposal_hash
                    or digest != action.approved_hash
                    or task.source_record_id != proposal.invoice_id
                    or isinstance(snapshot_company_id, bool)
                    or not isinstance(snapshot_company_id, int)
                    or snapshot_company_id != proposal.company_id
                    or conn.odoo_company_id != proposal.company_id
                ):
                    _fail_action(session, action, "proposal_validation_failed")
                    continue
                creds = decrypt_credentials(
                    conn.encrypted_credentials,
                    tenant_id=conn.tenant_id,
                    connection_id=conn.id,
                    encryption_version=conn.encryption_version,
                )
                auth = resolve_auth_material(conn.username, creds)
                action.status = "executing"
                action.version += 1
                _record_worker_history(session, action, "executing")
                session.flush()
                action.attempt_count += 1
                action.version += 1
                _record_worker_history(session, action, "executing")
                session.flush()
                receipt = create_invoice_activity(
                    base_url=conn.base_url,
                    database=conn.database_name,
                    transport=conn.selected_transport,
                    login=auth.login,
                    secret=auth.secret,
                    environment=get_settings().environment,
                    company_id=proposal.company_id,
                    invoice_id=proposal.invoice_id,
                    activity_type_id=proposal.activity_type_id,
                    summary=proposal.title,
                    date_deadline=proposal.date_deadline.isoformat(),
                    idempotency_marker=action.idempotency_marker,
                )
                action.external_activity_id = receipt["activity_id"]
                action.verified_at = datetime.now(UTC)
                action.status = "succeeded"
                action.error = None
                action.version += 1
                _record_worker_history(session, action, "succeeded")
                done += 1
            except (
                ConnectorError,
                CredentialDecryptionError,
                EncryptionConfigError,
                AuthMaterialError,
                ValidationError,
                ValueError,
                KeyError,
                TypeError,
                json.JSONDecodeError,
            ):
                action.version += 1
                if action.attempt_count < 3:
                    action.error = "external_execution_failed"
                    action.status = "queued"
                    _record_worker_history(
                        session, action, "retry_queued", detail="external_execution_failed"
                    )
                else:
                    action.error = "external_execution_failed"
                    action.status = "failed"
                    _record_worker_history(
                        session, action, "failed", detail="external_execution_failed"
                    )
        session.commit()
    finally:
        session.close()
    return done


def _record_worker_history(
    session, action: OperationAction, event: str, detail: str | None = None
) -> None:
    session.add(
        OperationActionHistory(
            action_id=action.id,
            task_id=action.task_id,
            tenant_id=action.tenant_id,
            actor_type="worker",
            actor_id="operations-worker",
            event=event,
            version=action.version,
            status=action.status,
            proposal_hash=action.proposal_hash,
            detail=detail,
        )
    )
    record_audit(
        session,
        action=f"operation_action.{event}",
        actor_type="worker",
        actor_id="operations-worker",
        tenant_id=action.tenant_id,
        resource_type="operation_action",
        resource_id=str(action.id),
        metadata={"detail": detail} if detail else {},
    )


def _fail_action(session, action: OperationAction, detail: str) -> None:
    action.status = "failed"
    action.error = detail
    action.lease_expires_at = None
    action.version += 1
    _record_worker_history(session, action, "failed", detail=detail)
    record_audit(
        session,
        action="operation_action.failed",
        actor_type="worker",
        actor_id="operations-worker",
        tenant_id=action.tenant_id,
        resource_type="operation_action",
        resource_id=str(action.id),
        metadata={"error_code": detail},
    )


def run_queued_workbench_actions_once() -> int:
    """Run only the explicit Phase 4B invoice-activity queue."""
    session = get_session_factory()()
    done = 0
    advisory_acquired = False
    try:
        if session.bind and session.bind.dialect.name == "postgresql":
            advisory_acquired = bool(
                session.execute(text("SELECT pg_try_advisory_lock(810051)")).scalar()
            )
            if not advisory_acquired:
                return 0
        now = datetime.now(UTC)
        actions = session.query(OperationAction).filter(
            OperationAction.workflow_key == "finance.prepare_collection_followup",
            or_(
                OperationAction.status == "queued",
                and_(
                    OperationAction.status == "executing",
                    OperationAction.lease_expires_at.is_not(None),
                    OperationAction.lease_expires_at < now,
                ),
            ),
        ).with_for_update(skip_locked=True).limit(1).all()
        for action in actions:
            # Claim one action in its own committed transaction.  No batch of
            # preselected rows may survive a mid-loop commit.
            action.status = "executing"
            action.version += 1
            action.claimed_at = now
            action.lease_expires_at = now + timedelta(minutes=5)
            _record_worker_history(session, action, "execution_started", PHASE4B_POLICY_ID)
            session.flush()
            session.commit()
            action = session.get(OperationAction, action.id)
            task = session.query(OperationTask).filter_by(
                id=action.task_id, tenant_id=action.tenant_id
            ).one_or_none()
            if task is None or task.source_type != "agent_workbench":
                _fail_action(session, action, "source_validation_failed")
                session.commit()
                continue
            try:
                proposal = CollectionProposal.model_validate_json(action.proposal_json)
                _, digest = canonical_collection_proposal(proposal)
                if digest != action.proposal_hash or digest != action.approved_hash:
                    _fail_action(session, action, "proposal_validation_failed")
                    session.commit()
                    continue
                if (
                    action.approved_by_user_id is None or action.approved_at is None
                    or action.workflow_key != "finance.prepare_collection_followup"
                    or action.workflow_config_version != 1
                    or proposal.service_request_id != uuid.UUID(task.source_reference or "00000000-0000-0000-0000-000000000000")
                    or proposal.tenant_id != action.tenant_id
                    or proposal.connection_id != task.source_connection_id
                ):
                    action.status, action.error = "failed", "stale_requires_reapproval"
                    action.lease_expires_at = None
                    action.version += 1
                    _record_worker_history(session, action, "failed", "stale_requires_reapproval")
                    session.commit()
                    continue
                conn = session.query(Connection).filter_by(
                    id=proposal.connection_id, tenant_id=action.tenant_id
                ).with_for_update().one_or_none()
                if (
                    conn is None or not conn.is_active or conn.status != "configured"
                    or conn.last_test_status != "success"
                    or conn.selected_transport not in ("xmlrpc", "json2")
                    or conn.odoo_company_id != proposal.company_id
                    or conn.provider != "odoo"
                    or conn.encrypted_credentials is None
                    or conn.encryption_version is None
                ):
                    action.status, action.error = "failed", "stale_requires_reapproval"
                    action.lease_expires_at = None
                    action.version += 1
                    _record_worker_history(session, action, "failed", "stale_requires_reapproval")
                    session.commit()
                    continue
                creds = decrypt_credentials(
                    conn.encrypted_credentials, tenant_id=conn.tenant_id,
                    connection_id=conn.id, encryption_version=conn.encryption_version,
                )
                auth = resolve_auth_material(conn.username, creds)
                items = session.query(OperationActionExecutionItem).filter_by(
                    action_id=action.id, tenant_id=action.tenant_id
                ).all()
                expected = {int(target["invoice_id"]) for target in proposal.target_records}
                actual = {item.invoice_id for item in items}
                valid_items = (
                    len(items) == len(actual) == len(expected)
                    and actual == expected
                    and all(
                        item.task_id == task.id
                        and item.idempotency_marker == sha256(
                            f"{action.id}:{item.invoice_id}:internal_invoice_activity_v1".encode()
                        ).hexdigest()
                        for item in items
                    )
                )
                if not valid_items or action.execution_policy_id != PHASE4B_POLICY_ID or not action.execution_deadline:
                    _fail_action(session, action, "execution_items_invalid")
                    session.commit()
                    continue
                if not preflight_invoice_collection_targets(
                    base_url=conn.base_url, database=conn.database_name,
                    transport=conn.selected_transport, login=auth.login,
                    secret=auth.secret, environment=get_settings().environment,
                    company_id=proposal.company_id, targets=proposal.target_records,
                    execution_date=datetime.now(UTC).date().isoformat(),
                ):
                    action.status, action.error = "failed", "stale_requires_reapproval"
                    action.lease_expires_at = None
                    action.version += 1
                    _record_worker_history(session, action, "preflight_failed", "stale_requires_reapproval")
                    _record_worker_history(session, action, "failed", "stale_requires_reapproval")
                    session.commit()
                    continue
                activity_type_id = resolve_standard_todo_activity_type(
                    base_url=conn.base_url, database=conn.database_name,
                    transport=conn.selected_transport, login=auth.login,
                    secret=auth.secret, environment=get_settings().environment,
                )
                action.status = "verifying"
                action.version += 1
                _record_worker_history(session, action, "verifying", PHASE4B_POLICY_ID)
                record_audit(
                    session, action="operation_action.verifying",
                    actor_type="worker", actor_id="operations-worker",
                    tenant_id=action.tenant_id, resource_type="operation_action",
                    resource_id=str(action.id),
                    metadata={"policy_id": PHASE4B_POLICY_ID},
                )
                session.commit()
                for item in items:
                    if item.status == "succeeded" and item.external_activity_id:
                        continue
                    if item.attempt_count >= 3:
                        item.status = "failed"
                        item.error = "attempt_limit_reached"
                        item.finished_at = datetime.now(UTC)
                        continue
                    target = next(
                        (x for x in proposal.target_records if x["invoice_id"] == item.invoice_id),
                        None,
                    )
                    if target is None:
                        item.status, item.error = "failed", "target_missing"
                        continue
                    item.status = "executing"
                    item.attempt_count += 1
                    item.started_at = item.started_at or datetime.now(UTC)
                    action.version += 1
                    _record_worker_history(session, action, "target_started", PHASE4B_POLICY_ID)
                    # Commit the claim and attempt before any network call.
                    # Thus connector failures cannot roll back the durable
                    # attempt counter and another worker cannot claim it.
                    session.flush()
                    session.commit()
                    item.status = "verifying"
                    session.flush()
                    existing = reconcile_invoice_activity(
                        base_url=conn.base_url, database=conn.database_name,
                        transport=conn.selected_transport, login=auth.login,
                        secret=auth.secret, environment=get_settings().environment,
                        company_id=proposal.company_id, invoice_id=item.invoice_id,
                        summary="Collection follow-up",
                        idempotency_marker=item.idempotency_marker,
                    )
                    if existing.get("activity_id"):
                        item.external_activity_id = existing["activity_id"]
                        item.receipt_json = json.dumps(existing, sort_keys=True)
                        item.status = "succeeded"
                        item.verified_at = datetime.now(UTC)
                        item.finished_at = datetime.now(UTC)
                        session.commit()
                        action.version += 1
                        _record_worker_history(session, action, "target_verified", PHASE4B_POLICY_ID)
                        continue
                    receipt = create_invoice_activity(
                        base_url=conn.base_url, database=conn.database_name,
                        transport=conn.selected_transport, login=auth.login,
                        secret=auth.secret, environment=get_settings().environment,
                        company_id=proposal.company_id, invoice_id=item.invoice_id,
                        activity_type_id=activity_type_id, summary="Collection follow-up",
                        date_deadline=action.execution_deadline or (
                            datetime.now(UTC).date() + timedelta(days=PHASE4B_DEADLINE_DAYS)
                        ).isoformat(),
                        idempotency_marker=item.idempotency_marker,
                    )
                    verified = reconcile_invoice_activity(
                        base_url=conn.base_url, database=conn.database_name,
                        transport=conn.selected_transport, login=auth.login,
                        secret=auth.secret, environment=get_settings().environment,
                        company_id=proposal.company_id, invoice_id=item.invoice_id,
                        summary="Collection follow-up",
                        idempotency_marker=item.idempotency_marker,
                    )
                    if not verified.get("activity_id"):
                        item.status, item.error = "failed", "verification_missing"
                        session.commit()
                        continue
                    item.external_activity_id = verified["activity_id"]
                    item.receipt_json = json.dumps(receipt, sort_keys=True)
                    item.status = "succeeded"
                    item.verified_at = datetime.now(UTC)
                    item.finished_at = datetime.now(UTC)
                    action.version += 1
                    _record_worker_history(session, action, "target_verified", PHASE4B_POLICY_ID)
                    session.commit()
                if items and all(i.status == "succeeded" for i in items):
                    action.status = "succeeded"
                    action.lease_expires_at = None
                    action.verified_at = datetime.now(UTC)
                    action.version += 1
                    _record_worker_history(session, action, "succeeded")
                    done += 1
                else:
                    action.status, action.error = "failed", "external_execution_failed"
                    action.version += 1
                    _record_worker_history(session, action, "failed", "external_execution_failed")
                session.commit()
            except (ActivityWritePolicyError, ConnectorError, CredentialDecryptionError, EncryptionConfigError,
                    AuthMaterialError, ValidationError, ValueError, TypeError, KeyError):
                session.rollback()
                action = session.get(OperationAction, action.id)
                if action:
                    action.status, action.error = "failed", "external_execution_failed"
                    action.lease_expires_at = None
                    item = session.query(OperationActionExecutionItem).filter_by(
                        action_id=action.id, tenant_id=action.tenant_id,
                    ).filter(
                        OperationActionExecutionItem.status.in_(("executing", "verifying"))
                    ).order_by(OperationActionExecutionItem.started_at.desc()).first()
                    if item:
                        item.status = "failed"
                        item.error = "external_execution_failed"
                        item.finished_at = datetime.now(UTC)
                    action.version += 1
                    _record_worker_history(session, action, "failed", "external_execution_failed")
                    session.commit()
        return done
    finally:
        if advisory_acquired:
            try:
                session.execute(text("SELECT pg_advisory_unlock(810051)"))
            except SQLAlchemyError:
                session.rollback()
        session.close()


def run_queued_collection_messages_once() -> int:
    """Process only the dedicated fixed invoice-chatter delivery queue."""
    session = get_session_factory()()
    delivered = 0
    try:
        if (
            session.bind
            and session.bind.dialect.name == "postgresql"
            and not session.execute(text("SELECT pg_try_advisory_xact_lock(810041)")).scalar()
        ):
            return 0
        message_ids = [
            row[0]
            for row in session.query(CollectionMessage.id)
            .filter_by(status="queued")
            .limit(20)
            .all()
        ]
        for message_id in message_ids:
            message = session.query(CollectionMessage).filter_by(
                id=message_id, status="queued"
            ).with_for_update().one_or_none()
            if message is None:
                continue
            message.status = "sending"
            message.attempt_count += 1
            message.version += 1
            _record_message_worker_event(session, message, "sending")
            session.flush()
            task = session.query(OperationTask).filter_by(
                id=message.task_id, tenant_id=message.tenant_id
            ).with_for_update().one_or_none()
            if task is None or task.source_connection_id is None or task.source_record_id is None:
                _fail_message(session, message, "source_validation_failed")
                continue
            connection = session.query(Connection).filter_by(
                id=task.source_connection_id, tenant_id=message.tenant_id
            ).with_for_update().one_or_none()
            if (
                connection is None
                or not connection.is_active
                or connection.last_test_status != "success"
                or connection.selected_transport not in ("xmlrpc", "json2")
                or connection.odoo_company_id is None
            ):
                _fail_message(session, message, "connection_unavailable")
                continue
            try:
                snapshot = json.loads(task.source_snapshot_json or "")
                snapshot_company_id = snapshot.get("company_id") if isinstance(snapshot, dict) else None
                approved_content, approved_digest = canonical_collection_message(
                    message.approved_content or "", message.approved_draft_version or 0
                )
                if (
                    approved_digest != message.approved_hash
                    or message.approved_hash != message.draft_hash
                    or message.approved_draft_version != message.draft_version
                    or message.approved_source_hash != message.source_hash
                    or message.approved_source_version != message.source_version
                    or snapshot_company_id != connection.odoo_company_id
                ):
                    _fail_message(session, message, "approval_validation_failed")
                    continue
                credentials = decrypt_credentials(
                    connection.encrypted_credentials,
                    tenant_id=connection.tenant_id,
                    connection_id=connection.id,
                    encryption_version=connection.encryption_version,
                )
                auth = resolve_auth_material(connection.username, credentials)
                partner_id = read_invoice_collection_target(
                    base_url=connection.base_url,
                    database=connection.database_name,
                    transport=connection.selected_transport,
                    login=auth.login,
                    secret=auth.secret,
                    environment=get_settings().environment,
                    company_id=connection.odoo_company_id,
                    invoice_id=task.source_record_id,
                    as_of_date=datetime.now(UTC).date(),
                    now=datetime.now(UTC),
                )
                _record_message_worker_event(
                    session, message, "policy_checked", detail="allowed"
                )
                source_hash = canonical_collection_source_identity(
                    connection_id=str(connection.id),
                    company_id=connection.odoo_company_id,
                    invoice_id=task.source_record_id,
                    partner_id=partner_id,
                    source_version=message.approved_source_version or 0,
                    source_snapshot=snapshot,
                )
                if (
                    source_hash != message.approved_source_hash
                    or partner_id != message.approved_partner_id
                ):
                    _fail_message(session, message, "source_identity_changed")
                    continue
                receipt = deliver_invoice_collection_message(
                    base_url=connection.base_url,
                    database=connection.database_name,
                    transport=connection.selected_transport,
                    login=auth.login,
                    secret=auth.secret,
                    environment=get_settings().environment,
                    company_id=connection.odoo_company_id,
                    invoice_id=task.source_record_id,
                    content=approved_content,
                    idempotency_marker=message.idempotency_marker,
                    expected_partner_id=message.approved_partner_id,
                    as_of_date=datetime.now(UTC).date(),
                    now=datetime.now(UTC),
                )
                message.status = "verifying"
                message.external_message_id = receipt["message_id"]
                message.version += 1
                _record_message_worker_event(session, message, "sent")
                _record_message_worker_event(session, message, "verifying")
                if receipt.get("verified") is not True:
                    raise ConnectorError("unsupported_response", "message not verified")
                message.verified_at = datetime.now(UTC)
                message.status = "succeeded"
                message.error = None
                message.version += 1
                _record_message_worker_event(session, message, "verified")
                _record_message_worker_event(session, message, "succeeded")
                delivered += 1
            except CollectionMessagePolicyError as exc:
                if isinstance(exc.code, str) and exc.code:
                    message.version += 1
                    message.status = "failed"
                    message.error = exc.code
                    _record_message_worker_event(
                        session, message, "policy_checked", detail=exc.code
                    )
                    _record_message_worker_event(
                        session, message, "failed", detail=exc.code
                    )
                else:
                    _record_delivery_failure(session, message)
            except (
                ConnectorError,
                CredentialDecryptionError,
                EncryptionConfigError,
                AuthMaterialError,
                ValidationError,
                ValueError,
                KeyError,
                TypeError,
                json.JSONDecodeError,
            ):
                _record_delivery_failure(session, message)
        session.commit()
        return delivered
    finally:
        session.close()


def _record_workbench_message_event(
    session, message: WorkbenchCollectionMessage, event: str, detail: str | None = None
) -> None:
    session.add(
        WorkbenchCollectionMessageEvent(
            message_id=message.id, tenant_id=message.tenant_id,
            service_request_id=message.service_request_id,
            actor_type="worker", actor_id="workbench-collection-delivery-worker",
            event=event, version=message.version,
            content_hash=message.approved_hash or message.draft_hash,
            source_hash=message.approved_source_hash or message.source_hash,
            detail=detail[:64] if detail else None,
        )
    )
    record_audit(
        session, action=f"workbench_collection_message_{event}",
        actor_type="worker", actor_id="workbench-collection-delivery-worker",
        tenant_id=message.tenant_id, resource_type="workbench_collection_message",
        resource_id=str(message.id),
        metadata={"action_id": str(message.action_id), "partner_id": message.approved_partner_id,
                  "anchor_invoice_id": message.delivery_anchor_invoice_id,
                  "attempt_count": message.attempt_count,
                  **({"error_code": detail} if detail else {})},
    )


def _fail_workbench_message(
    session, message: WorkbenchCollectionMessage, code: str, *, token: str | None = None
) -> None:
    token = token or message.claim_token
    if not token:
        return
    changed = session.execute(
        update(WorkbenchCollectionMessage).execution_options(synchronize_session=False)
        .where(
            WorkbenchCollectionMessage.id == message.id,
            WorkbenchCollectionMessage.claim_token == token,
            WorkbenchCollectionMessage.status.in_(("sending", "verifying")),
        )
        .values(
            status="failed", delivery_error_code=code, lease_expires_at=None,
            claimed_at=None, claim_token=None,
            version=WorkbenchCollectionMessage.version + 1,
        )
    )
    if changed.rowcount != 1:
        session.rollback()
        return
    current = session.get(WorkbenchCollectionMessage, message.id)
    _record_workbench_message_event(session, current, "failed", code)


def _requeue_workbench_message(
    session, message: WorkbenchCollectionMessage, code: str, *, token: str | None = None
) -> None:
    token = token or message.claim_token
    if not token:
        return
    changed = session.execute(
        update(WorkbenchCollectionMessage).execution_options(synchronize_session=False)
        .where(
            WorkbenchCollectionMessage.id == message.id,
            WorkbenchCollectionMessage.claim_token == token,
            WorkbenchCollectionMessage.status.in_(("sending", "verifying")),
        )
        .values(
            status="queued", delivery_error_code=code, lease_expires_at=None,
            claimed_at=None, claim_token=None,
            next_attempt_at=datetime.now(UTC) + timedelta(seconds=30),
            version=WorkbenchCollectionMessage.version + 1,
        )
    )
    if changed.rowcount != 1:
        session.rollback()
        return
    current = session.get(WorkbenchCollectionMessage, message.id)
    _record_workbench_message_event(session, current, "retry_queued", code)


def _lease_is_expired(lease_expires_at: datetime | None, now: datetime) -> bool:
    """Compare SQLite's naive timestamps and PostgreSQL's aware timestamps uniformly."""
    if lease_expires_at is None:
        return True
    if lease_expires_at.tzinfo is None:
        lease_expires_at = lease_expires_at.replace(tzinfo=UTC)
    return lease_expires_at <= now


def run_queued_workbench_collection_messages_once() -> int:
    """Deliver approved Workbench messages through the fixed Odoo adapter only."""
    session = get_session_factory()()
    delivered = 0
    acquired = False
    try:
        if session.bind and session.bind.dialect.name == "postgresql":
            acquired = bool(session.execute(text("SELECT pg_try_advisory_xact_lock(810061)")).scalar())
            if not acquired:
                return 0
        now = datetime.now(UTC)
        processed = 0
        while processed < 20:
            now = datetime.now(UTC)
            message = (
                session.query(WorkbenchCollectionMessage)
                .filter(
                    or_(
                        and_(
                            WorkbenchCollectionMessage.status == "queued",
                            WorkbenchCollectionMessage.attempt_count < 3,
                            or_(
                                WorkbenchCollectionMessage.next_attempt_at.is_(None),
                                WorkbenchCollectionMessage.next_attempt_at <= now,
                            ),
                        ),
                        and_(
                            WorkbenchCollectionMessage.status.in_(("sending", "verifying")),
                            WorkbenchCollectionMessage.lease_expires_at < now,
                        ),
                    )
                )
                .with_for_update(skip_locked=True)
                .first()
            )
            if message is None:
                break
            processed += 1
            claim_token = uuid.uuid4().hex
            prior_status = message.status
            claim_filter = [
                WorkbenchCollectionMessage.id == message.id,
                WorkbenchCollectionMessage.status == prior_status,
            ]
            if prior_status == "queued":
                claim_filter.extend(
                    [
                        WorkbenchCollectionMessage.claim_token.is_(None),
                        or_(
                            WorkbenchCollectionMessage.next_attempt_at.is_(None),
                            WorkbenchCollectionMessage.next_attempt_at <= now,
                        ),
                    ]
                )
            else:
                claim_filter.extend(
                    [
                        WorkbenchCollectionMessage.claim_token == message.claim_token,
                        WorkbenchCollectionMessage.lease_expires_at < now,
                    ]
                )
            claimed = session.execute(
                update(WorkbenchCollectionMessage).execution_options(synchronize_session=False)
                .where(*claim_filter)
                .values(
                    status="sending",
                    claimed_at=now,
                    lease_expires_at=now + timedelta(minutes=5),
                    claim_token=claim_token,
                    delivery_started_at=now,
                    version=WorkbenchCollectionMessage.version + 1,
                )
            )
            if claimed.rowcount != 1:
                session.rollback()
                continue
            session.refresh(message)
            _record_workbench_message_event(session, message, "sending")
            session.commit()
            message = session.get(WorkbenchCollectionMessage, message.id)
            if message is None:
                continue
            if message.attempt_count < 3:
                charged = session.execute(
                    update(WorkbenchCollectionMessage).execution_options(synchronize_session=False)
                    .where(
                        WorkbenchCollectionMessage.id == message.id,
                        WorkbenchCollectionMessage.claim_token == claim_token,
                        WorkbenchCollectionMessage.status == "sending",
                    )
                    .values(
                        attempt_count=WorkbenchCollectionMessage.attempt_count + 1,
                        version=WorkbenchCollectionMessage.version + 1,
                    )
                )
                if charged.rowcount != 1:
                    session.rollback()
                    continue
                session.commit()
                message = session.get(WorkbenchCollectionMessage, message.id)
                if message is None or message.claim_token != claim_token:
                    session.rollback()
                    continue
            delivery_call_started = False
            try:
                approved_content, digest = canonical_collection_message(
                    message.approved_content or "", message.approved_draft_version or 0
                )
                if (
                    digest != message.approved_hash or digest != message.draft_hash
                    or message.approved_draft_version != message.draft_version
                    or message.approved_source_hash != message.source_hash
                    or message.approved_source_version != message.source_version
                    or message.approved_partner_id != message.partner_id
                ):
                    _fail_workbench_message(session, message, "approval_invalid", token=claim_token)
                    session.commit()
                    continue
                action = session.query(OperationAction).filter_by(
                    id=message.action_id, tenant_id=message.tenant_id
                ).one_or_none()
                task = (
                    session.query(OperationTask)
                    .filter(OperationTask.tenant_id == message.tenant_id,
                            OperationTask.source_type == "agent_workbench",
                            OperationTask.source_reference == str(message.service_request_id),
                            OperationTask.source_signal == "finance.prepare_collection_followup",
                            OperationTask.id == (action.task_id if action else uuid.uuid4()))
                    .one_or_none()
                )
                connection = session.query(Connection).filter_by(
                    id=message.connection_id, tenant_id=message.tenant_id, provider="odoo"
                ).with_for_update().one_or_none()
                if (
                    action is None or task is None or connection is None
                    or not connection.is_active or connection.status != "configured"
                    or connection.last_test_status != "success"
                    or connection.selected_transport not in ("xmlrpc", "json2")
                    or connection.odoo_company_id != message.company_id
                    or connection.encrypted_credentials is None
                    or connection.encryption_version is None
                ):
                    _fail_workbench_message(
                        session, message, "source_changed_requires_reapproval", token=claim_token
                    )
                    session.commit()
                    continue
                payload = json.loads(message.source_evidence_json)
                invoice_ids = [int(value) for value in json.loads(message.invoice_ids_json)]
                records = payload["records"]
                items = session.query(OperationActionExecutionItem).filter_by(
                    action_id=action.id, task_id=task.id, tenant_id=message.tenant_id
                ).all()
                item_by_invoice = {item.invoice_id: item for item in items}
                target_items = [item_by_invoice.get(invoice_id) for invoice_id in invoice_ids]
                if (
                    len(invoice_ids) != len(set(invoice_ids))
                    or len(items) < len(invoice_ids)
                    or any(item is None or item.status != "succeeded"
                           or item.external_activity_id is None or item.verified_at is None
                           for item in target_items)
                ):
                    _fail_workbench_message(
                        session, message, "source_changed_requires_reapproval", token=claim_token
                    )
                    session.commit()
                    continue
                current_evidence = [
                    {"item_id": str(item_by_invoice[i].id), "invoice_id": i,
                     "external_activity_id": item_by_invoice[i].external_activity_id,
                     "verified_at": item_by_invoice[i].verified_at.isoformat()}
                    for i in sorted(invoice_ids)
                ]
                stored_evidence = sorted(payload["evidence"],
                                         key=lambda item: (int(item["invoice_id"]), str(item["item_id"])))
                if stored_evidence != current_evidence:
                    _fail_workbench_message(
                        session, message, "source_changed_requires_reapproval", token=claim_token
                    )
                    session.commit()
                    continue
                credentials = decrypt_credentials(
                    connection.encrypted_credentials, tenant_id=connection.tenant_id,
                    connection_id=connection.id, encryption_version=connection.encryption_version,
                )
                auth = resolve_auth_material(connection.username, credentials)
                live_records = []
                for record in records:
                    live = read_invoice_collection_snapshot(
                        base_url=connection.base_url, database=connection.database_name,
                        transport=connection.selected_transport, login=auth.login, secret=auth.secret,
                        environment=get_settings().environment, company_id=connection.odoo_company_id,
                        invoice_id=int(record["invoice_id"]), as_of_date=datetime.now(UTC).date(),
                        now=datetime.now(UTC),
                    )
                    if int(live["partner_id"]) != message.approved_partner_id or not _same_live_record(
                        record, live, message.company_id, payload.get("source_as_of")
                    ):
                        _fail_workbench_message(
                            session, message, "source_changed_requires_reapproval", token=claim_token
                        )
                        session.commit()
                        break
                    live_records.append({**record, "live_snapshot": live})
                else:
                    source_hash = canonical_grouped_source_identity(
                        tenant_id=message.tenant_id, service_request_id=message.service_request_id,
                        action_id=message.action_id, approved_proposal_hash=action.approved_hash or "",
                        connection_id=message.connection_id, company_id=message.company_id,
                        partner_id=message.approved_partner_id, invoice_records=live_records,
                        execution_evidence=current_evidence,
                        source_version=message.approved_source_version,
                    )
                    if source_hash != message.approved_source_hash:
                        _fail_workbench_message(
                            session, message, "source_changed_requires_reapproval", token=claim_token
                        )
                        session.commit()
                        continue
                    anchor = message.delivery_anchor_invoice_id or min(invoice_ids)
                    if anchor not in invoice_ids:
                        _fail_workbench_message(
                            session, message, "source_changed_requires_reapproval", token=claim_token
                        )
                        session.commit()
                        continue
                    anchored = session.execute(
                        update(WorkbenchCollectionMessage).execution_options(synchronize_session=False)
                        .where(
                            WorkbenchCollectionMessage.id == message.id,
                            WorkbenchCollectionMessage.claim_token == claim_token,
                            WorkbenchCollectionMessage.status == "sending",
                        )
                        .values(
                            delivery_anchor_invoice_id=anchor,
                            version=WorkbenchCollectionMessage.version + 1,
                        )
                    )
                    if anchored.rowcount != 1:
                        session.rollback()
                        continue
                    current = session.get(WorkbenchCollectionMessage, message.id)
                    _record_workbench_message_event(session, current, "policy_checked", "allowed")
                    # Persist the deterministic anchor and attempt before any
                    # network operation. A connector rollback must not erase
                    # either safety invariant.
                    session.commit()
                    message = session.get(WorkbenchCollectionMessage, message.id)
                    if (
                        message is None
                        or message.claim_token != claim_token
                        or message.status != "sending"
                        or message.lease_expires_at is None
                        or _lease_is_expired(message.lease_expires_at, datetime.now(UTC))
                    ):
                        continue
                    connection = session.query(Connection).filter_by(
                        id=message.connection_id,
                        tenant_id=message.tenant_id,
                        provider="odoo",
                    ).with_for_update().one_or_none()
                    if (
                        connection is None
                        or not connection.is_active
                        or connection.status != "configured"
                        or connection.last_test_status != "success"
                        or connection.selected_transport not in ("xmlrpc", "json2")
                        or connection.odoo_company_id != message.company_id
                        or connection.encrypted_credentials is None
                        or connection.encryption_version is None
                    ):
                        _fail_workbench_message(
                            session, message, "connection_changed_requires_reapproval", token=claim_token
                        )
                        session.commit()
                        continue
                    credentials = decrypt_credentials(
                        connection.encrypted_credentials,
                        tenant_id=connection.tenant_id,
                        connection_id=connection.id,
                        encryption_version=connection.encryption_version,
                    )
                    auth = resolve_auth_material(connection.username, credentials)
                    delivery_call_started = True
                    receipt = deliver_invoice_collection_message(
                        base_url=connection.base_url, database=connection.database_name,
                        transport=connection.selected_transport, login=auth.login, secret=auth.secret,
                        environment=get_settings().environment, company_id=connection.odoo_company_id,
                        invoice_id=anchor, content=approved_content,
                        idempotency_marker=message.idempotency_marker,
                        expected_partner_id=message.approved_partner_id,
                        as_of_date=datetime.now(UTC).date(), now=datetime.now(UTC),
                    )
                    current = session.get(WorkbenchCollectionMessage, message.id)
                    if (
                        current is None
                        or current.claim_token != claim_token
                        or current.status != "sending"
                    ):
                        session.rollback()
                        continue
                    message = current
                    if receipt.get("verified") is not True or not receipt.get("message_id"):
                        raise ConnectorError("unsupported_response", "message not verified")
                    changed = session.execute(
                        update(WorkbenchCollectionMessage).execution_options(synchronize_session=False)
                        .where(
                            WorkbenchCollectionMessage.id == message.id,
                            WorkbenchCollectionMessage.claim_token == claim_token,
                            WorkbenchCollectionMessage.status == "sending",
                        )
                        .values(
                            status="verifying",
                            external_message_id=receipt.get("message_id"),
                            version=WorkbenchCollectionMessage.version + 1,
                        )
                    )
                    if changed.rowcount != 1:
                        session.rollback()
                        continue
                    current = session.get(WorkbenchCollectionMessage, message.id)
                    _record_workbench_message_event(session, current, "verifying")
                    changed = session.execute(
                        update(WorkbenchCollectionMessage).execution_options(synchronize_session=False)
                        .where(
                            WorkbenchCollectionMessage.id == message.id,
                            WorkbenchCollectionMessage.claim_token == claim_token,
                            WorkbenchCollectionMessage.status == "verifying",
                        )
                        .values(
                            status="succeeded",
                            external_message_id=receipt.get("message_id"),
                            verified_at=datetime.now(UTC),
                            last_delivery_at=datetime.now(UTC),
                            delivery_error_code=None,
                            lease_expires_at=None,
                            claimed_at=None,
                            claim_token=None,
                            version=WorkbenchCollectionMessage.version + 1,
                        )
                    )
                    if changed.rowcount != 1:
                        session.rollback()
                        continue
                    current = session.get(WorkbenchCollectionMessage, message.id)
                    _record_workbench_message_event(session, current, "verified")
                    _record_workbench_message_event(session, current, "succeeded")
                    delivered += 1
                    session.commit()
            except CollectionMessagePolicyError as exc:
                session.rollback()
                message = session.get(WorkbenchCollectionMessage, message.id)
                if message is None:
                    continue
                if exc.code == "outside_contact_hours":
                    changed = session.execute(
                        update(WorkbenchCollectionMessage).execution_options(synchronize_session=False)
                        .where(
                            WorkbenchCollectionMessage.id == message.id,
                            WorkbenchCollectionMessage.claim_token == claim_token,
                            WorkbenchCollectionMessage.status == "sending",
                            WorkbenchCollectionMessage.attempt_count > 0,
                        )
                        .values(
                            status="queued",
                            attempt_count=WorkbenchCollectionMessage.attempt_count - 1,
                            delivery_error_code=exc.code,
                            claimed_at=None,
                            lease_expires_at=None,
                            claim_token=None,
                            next_attempt_at=datetime.now(UTC) + timedelta(minutes=15),
                            version=WorkbenchCollectionMessage.version + 1,
                        )
                    )
                    if changed.rowcount == 1:
                        current = session.get(WorkbenchCollectionMessage, message.id)
                        _record_workbench_message_event(session, current, "policy_blocked", exc.code)
                else:
                    _fail_workbench_message(
                        session, message, exc.code or "policy_unavailable", token=claim_token
                    )
                session.commit()
            except ConnectorError as exc:
                session.rollback()
                message = session.get(WorkbenchCollectionMessage, message.id)
                if message is None:
                    continue
                retryable_codes = {
                    "dns_resolution_failed", "connection_timeout",
                    "server_unreachable", "tls_error", "internal_connector_error",
                }
                if delivery_call_started and exc.code == "unsupported_response":
                    retryable_codes.add("unsupported_response")
                if exc.code in retryable_codes and message.attempt_count < 3:
                    _requeue_workbench_message(
                        session,
                        message,
                        "reconciliation_uncertain" if exc.code == "unsupported_response"
                        else "temporary_odoo_failure",
                        token=claim_token,
                    )
                else:
                    _fail_workbench_message(session, message, "delivery_failed", token=claim_token)
                session.commit()
            except (CredentialDecryptionError, EncryptionConfigError, AuthMaterialError,
                    ValidationError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                session.rollback()
                message = session.get(WorkbenchCollectionMessage, message.id)
                if message is None:
                    continue
                _fail_workbench_message(session, message, "delivery_invalid", token=claim_token)
                session.commit()
        return delivered
    finally:
        if acquired:
            try:
                session.execute(text("SELECT pg_advisory_unlock(810061)"))
            except SQLAlchemyError:
                session.rollback()
        session.close()


def _record_message_worker_event(
    session,
    message: CollectionMessage,
    event: str,
    detail: str | None = None,
) -> None:
    session.add(
        CollectionMessageEvent(
            message_id=message.id,
            task_id=message.task_id,
            tenant_id=message.tenant_id,
            actor_type="worker",
            actor_id="collection-message-worker",
            event=event,
            version=message.version,
            status=message.status,
            content_hash=message.approved_hash or message.draft_hash,
            detail=detail,
        )
    )


def _record_delivery_failure(session, message: CollectionMessage) -> None:
    message.version += 1
    message.error = "delivery_failed"
    if message.attempt_count < 3:
        message.status = "queued"
        _record_message_worker_event(
            session, message, "retry_queued", detail="delivery_failed"
        )
    else:
        message.status = "failed"
        _record_message_worker_event(
            session, message, "failed", detail="delivery_failed"
        )


def _fail_message(session, message: CollectionMessage, detail: str) -> None:
    message.status = "failed"
    message.error = detail
    message.version += 1
    _record_message_worker_event(session, message, "failed", detail=detail)


def scan_connections_once() -> int:
    """Scan each explicitly company-scoped connection independently."""
    session = get_session_factory()()
    scanned = 0
    try:
        connections = session.query(Connection).filter(
            Connection.provider == "odoo", Connection.is_active.is_(True),
            Connection.last_test_status == "success",
            Connection.selected_transport.in_(("xmlrpc", "json2")),
            Connection.odoo_company_id.is_not(None),
        ).all()
        for conn in connections:
            actor = session.get(User, conn.created_by_user_id) if conn.created_by_user_id else None
            if actor is None or not actor.is_active:
                continue
            try:
                created = scan_overdue_invoices(
                    session, connection=conn, company_id=conn.odoo_company_id, actor=actor
                )
                record_audit(session, action="connection.overdue_invoice_sync",
                    actor_type="worker", actor_id=str(conn.id), tenant_id=conn.tenant_id,
                    resource_type="connection", resource_id=str(conn.id),
                    metadata={"company_id": conn.odoo_company_id, "created": created})
                session.commit()
                scanned += 1
            except (ConnectorError, CredentialDecryptionError, EncryptionConfigError,
                    AuthMaterialError, ValueError, TypeError):
                session.rollback()
                # The exception may contain upstream detail; audit only a static outcome.
                record_audit(session, action="connection.overdue_invoice_sync_failed",
                    actor_type="worker", actor_id=str(conn.id), tenant_id=conn.tenant_id,
                    resource_type="connection", resource_id=str(conn.id),
                    metadata={"company_id": conn.odoo_company_id})
                session.commit()
        return scanned
    finally:
        session.close()


def main() -> None:
    while True:
        generate_missing_ai_proposals_once()
        run_queued_actions_once()
        run_queued_workbench_actions_once()
        run_queued_workbench_collection_messages_once()
        run_queued_collection_messages_once()
        scan_connections_once()
        session = get_session_factory()()
        try:
            generate_occurrences(session)
            session.commit()
        finally:
            session.close()
        time.sleep(15)

if __name__ == "__main__":
    main()