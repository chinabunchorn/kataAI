# Backend agreement compatibility fixture

The three files under `app/` are unmodified backend contract, proposal and result
decoder source from `chinabunchorn/kataAI`, branch `backend`, commit
`49f94011b0f824d45dc1bf012473b3af978f3b77`:

- `backend/app/executor_contract.py`
- `backend/app/proposals.py`
- `backend/app/executor_results.py`

They let stdlib unittest exercise the exact backend types without importing the
FastAPI/SQLAlchemy application or adding its branch to this checkout. Test imports
are isolated in `sys.modules`. These fixtures are not production dependencies;
the adapter loads `app.executor_contract` and `app.executor_results` from the
actual backend application. Update the fixture and compatibility tests together
when the backend agreement changes.
