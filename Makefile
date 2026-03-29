.PHONY: demo clean logs replay status

demo:
	docker compose up --build

clean:
	docker compose down -v
	rm -rf captures/

logs:
	docker compose logs -f

replay:
	@echo "Open http://localhost:3000 and click Replay after an attack completes"
	@echo "Or POST to http://localhost:3000/api/replay/start?speed=2"

status:
	@docker compose ps
