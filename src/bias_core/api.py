from ninja import Router

router = Router(tags=["System"])


@router.get("/status")
def system_status(request):
    from bias_core.runtime_state import get_runtime_status
    runtime = get_runtime_status()
    return {
        "status": runtime.state,
        "state": runtime.state,
        "current_version": runtime.current_version,
    }
