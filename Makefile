PYTHON ?= python
RESULTS ?= results/reproduction
SYSTEMS ?= b0 b1

.PHONY: help test datasets evaluate aggregate cost review reproduce clean-results

help:
	@echo "SlopGate evaluation commands:"
	@echo "  make test          Run all unit tests"
	@echo "  make datasets      Generate D1, D3, and D4 datasets"
	@echo "  make evaluate      Run deterministic B0/B1 evaluations"
	@echo "  make aggregate     Aggregate evaluation predictions"
	@echo "  make cost          Generate cost summaries"
	@echo "  make review        Export D3/D4 review summaries"
	@echo "  make reproduce     Run the complete offline workflow"
	@echo "  make clean-results Remove reproduction outputs"

test:
	$(PYTHON) -W ignore -m unittest discover -s tests -v

datasets:
	$(PYTHON) -m slopgate.datasets.d1
	$(PYTHON) -m slopgate.datasets.d3_d4

evaluate:
	@mkdir -p $(RESULTS)
	@for dataset in d1 d3 d4; do \
		echo "===== Evaluating $$dataset ====="; \
		$(PYTHON) -m slopgate.evaluation.resume \
			--data corpus/$$dataset/$$dataset.jsonl \
			--systems $(SYSTEMS) \
			--out $(RESULTS)/$$dataset || exit $$?; \
	done

aggregate:
	@for dataset in d1 d3 d4; do \
		echo "===== Aggregating $$dataset ====="; \
		$(PYTHON) -m slopgate.evaluation.aggregate \
			--input $(RESULTS)/$$dataset \
			--out $(RESULTS)/$$dataset/comparison || exit $$?; \
	done

cost:
	@for dataset in d1 d3 d4; do \
		echo "===== Cost accounting: $$dataset ====="; \
		$(PYTHON) -m slopgate.evaluation.cost \
			--input $(RESULTS)/$$dataset \
			--out $(RESULTS)/$$dataset/cost || exit $$?; \
	done

review:
	@for dataset in d3 d4; do \
		echo "===== Reviewing $$dataset ====="; \
		$(PYTHON) -m slopgate.evaluation.review \
			--data corpus/$$dataset/$$dataset.jsonl \
			--predictions $(RESULTS)/$$dataset/b1_predictions.jsonl \
			--limit 0 \
			--export $(RESULTS)/$$dataset/review.json || exit $$?; \
	done

reproduce: test datasets evaluate aggregate cost review
	@echo "===== REPRODUCTION COMPLETE ====="
	@echo "Outputs saved under $(RESULTS)"

clean-results:
	rm -rf $(RESULTS)
