IMAGE ?= book2video:latest
BOOK ?= /data/book.epub
OUT ?= /out/pilot.mp4
ALL_OUT ?= /out/book.mp4
CHAPTER ?= 4
SPEED ?= 1.2

.PHONY: image build voices inspect pilot all test check shell clean

image:
	docker compose build

# Alias kept for muscle memory: `make build` builds the image, not a video.
build: image

voices:
	docker compose run --rm book2video voices

inspect:
	docker compose run --rm book2video inspect "$(BOOK)"

pilot:
	docker compose run --rm book2video build "$(BOOK)" \
		--chapter $(CHAPTER) --voice ru_m5 --sidebar-voice ru_f1 \
		--speed $(SPEED) --out "$(OUT)"

all:
	docker compose run --rm book2video build "$(BOOK)" \
		--all --voice ru_m5 --sidebar-voice ru_f1 \
		--speed $(SPEED) --out "$(ALL_OUT)"

test:
	docker compose run --rm --entrypoint sh book2video -c \
		'cd /data/book2video && python -m unittest discover -s tests -t tests -v'

check: test
	docker compose run --rm book2video --help >/dev/null

shell:
	docker compose run --rm --entrypoint bash book2video

clean:
	find out -mindepth 1 ! -name .gitkeep -delete
